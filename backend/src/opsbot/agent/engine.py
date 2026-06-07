from __future__ import annotations

from datetime import UTC, datetime

import structlog

from opsbot.agent.llm import LLMClient
from opsbot.agent.memory import ConversationMemory
from opsbot.agent.prompts.system import SYSTEM_PROMPT
from opsbot.mcp.manager import MCPManager, get_manager
from opsbot.models.db import RiskLevel
from opsbot.tools.registry import get_human_description, get_tool_risk

log = structlog.get_logger(__name__)

# Redis key pattern: opsbot:tokens:{user_id}:{YYYY-MM-DD}
_TOKEN_KEY_PREFIX = "opsbot:tokens"
_TOKEN_KEY_TTL = 90000  # 25 hours — covers timezone skew

MAX_ITERATIONS = 15
MAX_MESSAGE_LENGTH = 4000  # chars; guard against prompt injection via oversized messages

# Roles allowed to execute WRITE operations (DESTRUCTIVE always requires approval)
_WRITE_ALLOWED_ROLES = {"developer", "sre", "admin"}


class NeedsApprovalError(Exception):
    """Raised when the agent wants to execute a DESTRUCTIVE tool that needs approval."""

    def __init__(self, tool_name: str, tool_args: dict, description: str, tool_call_id: str = "") -> None:
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.description = description
        self.tool_call_id = tool_call_id
        self.risk_level = get_tool_risk(tool_name)
        super().__init__(f"Approval required for {tool_name}")


class AgentResult:
    def __init__(self, content: str, tool_calls_made: list[dict], status: str) -> None:
        self.content = content
        self.tool_calls_made = tool_calls_made
        self.status = status  # "completed" | "needs_approval" | "failed"


class AgentEngine:
    def __init__(
        self,
        mcp_manager: MCPManager | None = None,
        memory: ConversationMemory | None = None,
    ) -> None:
        self._mcp = mcp_manager or get_manager()
        self._memory = memory or ConversationMemory()
        self._llm = LLMClient()

    def _system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(today=datetime.now(UTC).strftime("%Y-%m-%d"))

    async def _check_token_budget(self, user_id: str) -> None:
        from opsbot.config.settings import get_settings
        s = get_settings()
        if s.litellm_daily_token_limit <= 0:
            return
        r = await self._memory._get_redis()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"{_TOKEN_KEY_PREFIX}:{user_id}:{today}"
        used_raw = await r.get(key)
        used = int(used_raw) if used_raw else 0
        if used >= s.litellm_daily_token_limit:
            log.warning("agent.token_budget.exceeded", user=user_id, used=used, limit=s.litellm_daily_token_limit)
            raise PermissionError(
                f"Daily token budget exceeded ({used:,}/{s.litellm_daily_token_limit:,} tokens used). "
                "Budget resets at midnight UTC."
            )

    async def _record_token_usage(self, user_id: str, tokens: int) -> None:
        if tokens <= 0:
            return
        try:
            r = await self._memory._get_redis()
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            key = f"{_TOKEN_KEY_PREFIX}:{user_id}:{today}"
            await r.incrby(key, tokens)
            await r.expire(key, _TOKEN_KEY_TTL)
        except Exception as exc:
            log.warning("agent.token_tracking.failed", error=str(exc))

    async def process(
        self,
        message: str,
        channel_id: str,
        requester_slack_id: str,
        thread_ts: str | None = None,
        task_id: str | None = None,
        requester_role: str = "developer",
    ) -> AgentResult:
        log.info("agent.process", channel=channel_id, user=requester_slack_id, message=message[:80])

        # Guard against oversized/injected messages
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[:MAX_MESSAGE_LENGTH] + "\n[message truncated]"

        await self._check_token_budget(requester_slack_id)

        history = await self._memory.get_history(channel_id, thread_ts)
        initial_length = len(history)
        history.append({"role": "user", "content": message})

        tools = self._mcp.get_all_tools()
        tool_calls_made: list[dict] = []
        iterations = 0

        while iterations < MAX_ITERATIONS:
            iterations += 1
            response = await self._llm.complete(
                messages=history,
                tools=tools if tools else None,
                system=self._system_prompt(),
            )

            response_msg = response.to_message()
            history.append(response_msg)
            await self._record_token_usage(requester_slack_id, response.usage.get("total_tokens", 0))

            if not response.tool_calls:
                # Final answer — save only the messages added this invocation
                final_content = response.content or "Done."
                await self._memory.append_many(channel_id, history[initial_length:], thread_ts)
                log.info("agent.done", iterations=iterations, tool_calls=len(tool_calls_made))
                return AgentResult(final_content, tool_calls_made, "completed")

            # Process tool calls
            tool_result_messages: list[dict] = []

            for tc in response.tool_calls:
                tool_name = tc.name
                tool_args = tc.args
                risk = get_tool_risk(tool_name)

                log.info("agent.tool_call", tool=tool_name, risk=risk, iteration=iterations)

                if risk == RiskLevel.DESTRUCTIVE:
                    description = get_human_description(tool_name, tool_args)
                    await self._memory.append_many(channel_id, history[initial_length:], thread_ts)
                    raise NeedsApprovalError(tool_name, tool_args, description, tool_call_id=tc.id)

                # Enforce WRITE operations are blocked for readonly users
                if risk == RiskLevel.WRITE and requester_role not in _WRITE_ALLOWED_ROLES:
                    result_text = (
                        f"Permission denied: your role ({requester_role}) cannot perform "
                        f"write operations. Ask an admin or SRE to run this."
                    )
                    tool_calls_made.append({"tool": tool_name, "args": tool_args, "success": False, "error": "permission_denied"})
                    tool_result_messages.append(self._llm.build_tool_result_message(tc.id, result_text))
                    continue

                # Execute the tool
                try:
                    result_text = await self._mcp.call_tool(tool_name, tool_args)
                    tool_calls_made.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result_length": len(result_text),
                        "success": True,
                    })
                except Exception as exc:
                    log.error("agent.tool_error", tool=tool_name, error=str(exc))
                    # Don't leak internal error details to the LLM response
                    result_text = f"Tool {tool_name} failed. Check logs for details."
                    tool_calls_made.append({"tool": tool_name, "args": tool_args, "success": False, "error": str(exc)})

                tool_result_messages.append(
                    self._llm.build_tool_result_message(tc.id, result_text)
                )

            history.extend(tool_result_messages)

        await self._memory.append_many(channel_id, history[initial_length:], thread_ts)
        return AgentResult("I've reached the maximum number of steps. Please try a more specific request.", tool_calls_made, "failed")

    async def resume_after_approval(
        self,
        tool_name: str,
        tool_args: dict,
        original_tool_call_id: str,
        channel_id: str,
        thread_ts: str | None = None,
    ) -> AgentResult:
        """Resume agent execution after a destructive tool has been approved."""
        log.info("agent.resume", tool=tool_name, channel=channel_id)

        history = await self._memory.get_history(channel_id, thread_ts)
        initial_length = len(history)
        tools = self._mcp.get_all_tools()
        tool_calls_made: list[dict] = []

        try:
            result_text = await self._mcp.call_tool(tool_name, tool_args)
            tool_calls_made.append({"tool": tool_name, "args": tool_args, "success": True})
        except Exception as exc:
            result_text = f"Error executing {tool_name}: {exc}"
            tool_calls_made.append({"tool": tool_name, "success": False, "error": str(exc)})

        tool_result_msg = self._llm.build_tool_result_message(original_tool_call_id, result_text)
        history.append(tool_result_msg)

        # Continue the ReAct loop
        iterations = 0
        while iterations < MAX_ITERATIONS:
            iterations += 1
            response = await self._llm.complete(messages=history, tools=tools, system=self._system_prompt())
            response_msg = response.to_message()
            history.append(response_msg)

            if not response.tool_calls:
                await self._memory.append_many(channel_id, history[initial_length:], thread_ts)
                return AgentResult(response.content or "Done.", tool_calls_made, "completed")

            tool_result_messages: list[dict] = []
            for tc in response.tool_calls:
                risk = get_tool_risk(tc.name)
                if risk == RiskLevel.DESTRUCTIVE:
                    raise NeedsApprovalError(tc.name, tc.args, get_human_description(tc.name, tc.args))
                try:
                    result_text = await self._mcp.call_tool(tc.name, tc.args)
                    tool_calls_made.append({"tool": tc.name, "args": tc.args, "success": True})
                except Exception as exc:
                    result_text = f"Error: {exc}"
                    tool_calls_made.append({"tool": tc.name, "success": False, "error": str(exc)})
                tool_result_messages.append(self._llm.build_tool_result_message(tc.id, result_text))

            history.extend(tool_result_messages)

        await self._memory.append_many(channel_id, history[initial_length:], thread_ts)
        return AgentResult("Operation completed.", tool_calls_made, "completed")
