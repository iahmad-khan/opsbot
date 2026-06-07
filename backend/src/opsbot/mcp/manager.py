from __future__ import annotations

import asyncio
from typing import Any

import structlog

from opsbot.mcp.client import MCPClient
from opsbot.mcp.servers import MCPServerConfig, get_server_configs

log = structlog.get_logger(__name__)

_manager: MCPManager | None = None


class MCPManager:
    """Manages a pool of MCP server connections and routes tool calls."""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._tool_index: dict[str, MCPClient] = {}  # litellm_tool_name → client
        self._initialized = False

    async def initialize(self, configs: list[MCPServerConfig] | None = None) -> None:
        if self._initialized:
            return
        if configs is None:
            configs = get_server_configs()

        connect_tasks = []
        for cfg in configs:
            client = MCPClient(cfg)
            self._clients[cfg.name] = client
            connect_tasks.append(self._connect_one(client))

        results = await asyncio.gather(*connect_tasks, return_exceptions=True)
        for cfg, result in zip(configs, results, strict=False):
            if isinstance(result, Exception):
                log.warning("mcp.server.unavailable", server=cfg.name, error=str(result))
            else:
                client = self._clients[cfg.name]
                for tool_def in client.to_litellm_tools():
                    self._tool_index[tool_def["function"]["name"]] = client

        self._initialized = True
        log.info(
            "mcp.manager.ready",
            servers=list(self._clients.keys()),
            total_tools=len(self._tool_index),
        )

    async def _connect_one(self, client: MCPClient) -> None:
        await client.connect()

    async def shutdown(self) -> None:
        await asyncio.gather(
            *[c.disconnect() for c in self._clients.values()],
            return_exceptions=True,
        )
        self._clients.clear()
        self._tool_index.clear()
        self._initialized = False

    def get_all_tools(self) -> list[dict]:
        tools = []
        for client in self._clients.values():
            if client.is_connected:
                tools.extend(client.to_litellm_tools())
        return tools

    async def call_tool(self, litellm_tool_name: str, arguments: dict[str, Any]) -> str:
        client = self._tool_index.get(litellm_tool_name)
        if client is None:
            raise ValueError(f"No MCP server handles tool: {litellm_tool_name}")

        # Strip server prefix: "kubernetes__list_pods" → "list_pods"
        _, _, mcp_tool_name = litellm_tool_name.partition("__")
        return await client.call_tool(mcp_tool_name, arguments)

    def get_server_status(self) -> dict[str, str]:
        return {
            name: "connected" if client.is_connected else "disconnected"
            for name, client in self._clients.items()
        }

    def get_client(self, server_name: str) -> MCPClient | None:
        return self._clients.get(server_name)


def get_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
