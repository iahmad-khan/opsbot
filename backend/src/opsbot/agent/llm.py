from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import litellm
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)

litellm.set_verbose = False


class ToolCall(dict):
    """Lightweight wrapper around a LiteLLM tool call dict."""

    @property
    def id(self) -> str:
        return self["id"]

    @property
    def name(self) -> str:
        return self["function"]["name"]

    @property
    def args(self) -> dict:
        raw = self["function"].get("arguments", "{}")
        if isinstance(raw, str):
            return json.loads(raw)
        return raw


class LLMResponse:
    def __init__(self, raw: Any) -> None:
        self._raw = raw

    @property
    def content(self) -> str | None:
        choice = self._raw.choices[0]
        return choice.message.content

    @property
    def tool_calls(self) -> list[ToolCall]:
        choice = self._raw.choices[0]
        calls = choice.message.tool_calls or []
        return [ToolCall({"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}) for c in calls]

    @property
    def finish_reason(self) -> str:
        return self._raw.choices[0].finish_reason

    @property
    def usage(self) -> dict:
        u = self._raw.usage
        return {
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "total_tokens": u.total_tokens,
        }

    def to_message(self) -> dict:
        msg: dict[str, Any] = {"role": "assistant"}
        if self.content:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = [dict(tc) for tc in self.tool_calls]
        return msg


class LLMClient:
    def __init__(self, model: str | None = None) -> None:
        s = get_settings()
        self.model = model or s.litellm_default_model
        self.max_tokens = s.litellm_max_tokens
        self.temperature = s.litellm_temperature
        self.max_retries = s.litellm_max_retries
        self.timeout = s.litellm_timeout
        self._configure_providers(s)

    def _configure_providers(self, s) -> None:
        if s.anthropic_api_key:
            import anthropic  # noqa: F401
            litellm.anthropic_key = s.anthropic_api_key
        if s.openai_api_key:
            litellm.openai_key = s.openai_api_key
        if s.google_api_key:
            litellm.vertex_key = s.google_api_key

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict = "auto",
        model: str | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        all_messages = list(messages)
        if system:
            all_messages = [{"role": "system", "content": system}] + all_messages

        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": all_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout": self.timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        log.debug("llm.complete", model=kwargs["model"], messages_count=len(all_messages), tools_count=len(tools or []))

        try:
            response = await litellm.acompletion(**kwargs)
            result = LLMResponse(response)
            log.debug("llm.complete.done", finish_reason=result.finish_reason, usage=result.usage)
            return result
        except Exception as exc:
            log.error("llm.complete.error", error=str(exc), model=kwargs["model"])
            raise

    async def stream_complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        all_messages = list(messages)
        if system:
            all_messages = [{"role": "system", "content": system}] + all_messages

        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": all_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
            "timeout": self.timeout,
        }
        if tools:
            kwargs["tools"] = tools

        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    def build_tool_result_message(self, tool_call_id: str, content: str) -> dict:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }

    def list_models(self) -> list[str]:
        return [
            "claude-opus-4-8",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "gpt-4o",
            "gpt-4o-mini",
            "gemini/gemini-1.5-pro",
            "gemini/gemini-1.5-flash",
            "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
            "ollama/llama3.2",
        ]
