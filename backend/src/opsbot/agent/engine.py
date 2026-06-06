from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import structlog

from opsbot.agent.llm import LLMClient, LLMResponse
from opsbot.agent.memory import ConversationMemory
from opsbot.agent.prompts.system import SYSTEM_PROMPT
from opsbot.mcp.manager import MCPManager, get_manager
from opsbot.models.db import RiskLevel, TaskStatus
from opsbot.tools.registry import get_tool_risk, get_human_description

log = structlog.get_logger(__name__)

MAX_ITERATIONS = 15


class NeedsApprovalError(Exception):
    """Raised when the agent wants to execute a DESTRUCTIVE tool that needs approval."""

    def __init__(self, tool_name: str, tool_args: dict, description: str) -> None:
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.description = description
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
        return SYSTEM_PROMPT.format(today=datetime.now(timezone.utc).strftime("%Y-%m-%d"))

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

        history = await self._memory.get_history(channel_id, thread_ts)
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

            if not response.tool_calls:
                # Final answer
                final_content = response.content or "Done."
                await self._memory.append_many(channel_id, [{"role": "user", "content": message}] if not history[:-2] else [], thread_ts)
                await self._memory.append(channel_id, response_msg, thread_ts)
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
                    # Persist conversation state before pausing
                    await self._memory.append_many(channel_id, history[-len(history):], thread_ts)
                    raise NeedsApprovalError(tool_name, tool_args, description)

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
                    result_text = f"Error executing {tool_name}: {exc}"
                    tool_calls_made.append({"tool": tool_name, "args": tool_args, "success": False, "error": str(exc)})
                    log.error("agent.tool_error", tool=tool_name, error=str(exc))

                tool_result_messages.append(
                    self._llm.build_tool_result_message(tc.id, result_text)
                )

            history.extend(tool_result_messages)

        await self._memory.append_many(channel_id, history, thread_ts)
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
                await self._memory.append(channel_id, response_msg, thread_ts)
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

        await self._memory.append_many(channel_id, history, thread_ts)
        return AgentResult("Operation completed.", tool_calls_made, "completed")
