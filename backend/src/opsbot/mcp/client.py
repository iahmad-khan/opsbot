from __future__ import annotations

import asyncio
from typing import Any

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool

from opsbot.mcp.servers import MCPServerConfig

log = structlog.get_logger(__name__)

_SENSITIVE_KEY_FRAGMENTS = frozenset({"token", "password", "secret", "key", "credential", "auth", "api_key"})


def _redact_args(args: dict[str, Any]) -> dict[str, Any]:
    """Replace values whose key names suggest secrets with '***'."""
    return {
        k: "***" if any(frag in k.lower() for frag in _SENSITIVE_KEY_FRAGMENTS) else v
        for k, v in args.items()
    }


class MCPClient:
    """Async stdio MCP client for a single server."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: ClientSession | None = None
        self._tools: list[Tool] = []
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def tools(self) -> list[Tool]:
        return self._tools

    async def connect(self) -> None:
        async with self._lock:
            if self._session is not None:
                return
            try:
                params = StdioServerParameters(
                    command=self.config.command,
                    args=self.config.args,
                    env={**self.config.env},
                )
                read, write = await stdio_client(params).__aenter__()
                self._session = ClientSession(read, write)
                await self._session.__aenter__()
                await self._session.initialize()
                result = await self._session.list_tools()
                self._tools = result.tools
                log.info("mcp.connected", server=self.config.name, tools=len(self._tools))
            except Exception as exc:
                log.error("mcp.connect.failed", server=self.config.name, error=str(exc))
                self._session = None
                raise

    async def disconnect(self) -> None:
        async with self._lock:
            if self._session:
                import contextlib
                with contextlib.suppress(Exception):
                    await self._session.__aexit__(None, None, None)
                self._session = None

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            await self.connect()

        log.debug("mcp.tool.call", server=self.config.name, tool=tool_name, args=_redact_args(arguments))
        try:
            result = await self._session.call_tool(tool_name, arguments)
            # MCP result content is a list of content items
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                elif hasattr(content, "data"):
                    parts.append(str(content.data))
            text = "\n".join(parts)
            log.debug("mcp.tool.result", server=self.config.name, tool=tool_name, length=len(text))
            return text
        except Exception as exc:
            log.error("mcp.tool.error", server=self.config.name, tool=tool_name, error=str(exc))
            raise

    def to_litellm_tools(self) -> list[dict]:
        """Convert MCP tools to LiteLLM/OpenAI tool format."""
        result = []
        for tool in self._tools:
            schema = tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}}
            result.append({
                "type": "function",
                "function": {
                    "name": f"{self.config.name}__{tool.name}",
                    "description": tool.description or "",
                    "parameters": schema,
                },
                "_mcp_server": self.config.name,
                "_mcp_tool": tool.name,
            })
        return result

    @property
    def is_connected(self) -> bool:
        return self._session is not None
