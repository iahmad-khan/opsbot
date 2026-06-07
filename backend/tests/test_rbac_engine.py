"""Tests for RBAC enforcement in the agent engine."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")

from opsbot.agent.engine import _WRITE_ALLOWED_ROLES, AgentEngine, NeedsApprovalError
from opsbot.models.db import RiskLevel


class TestWriteAllowedRoles:
    def test_developer_allowed(self):
        assert "developer" in _WRITE_ALLOWED_ROLES

    def test_sre_allowed(self):
        assert "sre" in _WRITE_ALLOWED_ROLES

    def test_admin_allowed(self):
        assert "admin" in _WRITE_ALLOWED_ROLES

    def test_readonly_not_allowed(self):
        assert "readonly" not in _WRITE_ALLOWED_ROLES


class TestMessageLengthGuard:
    @pytest.mark.asyncio
    async def test_message_truncated_at_limit(self):
        """Messages longer than MAX_MESSAGE_LENGTH are truncated before going to the LLM."""
        from opsbot.agent.engine import MAX_MESSAGE_LENGTH

        oversized = "x" * (MAX_MESSAGE_LENGTH + 500)

        mock_mcp = MagicMock()
        mock_mcp.get_all_tools.return_value = []
        mock_memory = AsyncMock()
        mock_memory.get_history.return_value = []
        mock_memory.append_many = AsyncMock()
        mock_memory.append = AsyncMock()

        # LLM returns a final answer immediately (no tool calls)
        mock_response = MagicMock()
        mock_response.tool_calls = []
        mock_response.content = "ok"
        mock_response.to_message.return_value = {"role": "assistant", "content": "ok"}

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=mock_response)

        engine = AgentEngine(mcp_manager=mock_mcp, memory=mock_memory)
        engine._llm = mock_llm

        await engine.process(
            message=oversized,
            channel_id="C1",
            requester_slack_id="U1",
        )

        # The message passed to LLM history should be truncated
        call_args = mock_llm.complete.call_args
        messages = call_args[1]["messages"] if call_args[1] else call_args[0][0]
        user_message = next((m for m in messages if m.get("role") == "user"), None)
        assert user_message is not None
        assert len(user_message["content"]) <= MAX_MESSAGE_LENGTH + len("\n[message truncated]") + 10


class TestReadonlyRoleBlocked:
    @pytest.mark.asyncio
    async def test_readonly_cannot_run_write_tool(self):
        """A readonly user should get permission denied when WRITE tool is called."""
        mock_mcp = MagicMock()
        mock_mcp.get_all_tools.return_value = []
        mock_memory = AsyncMock()
        mock_memory.get_history.return_value = []
        mock_memory.append_many = AsyncMock()
        mock_memory.append = AsyncMock()

        # First LLM call returns a WRITE tool call
        tool_call = MagicMock()
        tool_call.name = "k8s_restart_deployment"
        tool_call.args = {"deployment": "checkout", "namespace": "default"}
        tool_call.id = "call_1"

        mock_response_with_tool = MagicMock()
        mock_response_with_tool.tool_calls = [tool_call]
        mock_response_with_tool.content = None
        mock_response_with_tool.to_message.return_value = {
            "role": "assistant", "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "k8s_restart_deployment", "arguments": "{}"}}]
        }

        # Second LLM call returns final answer
        mock_response_final = MagicMock()
        mock_response_final.tool_calls = []
        mock_response_final.content = "Sorry, you don't have permission."
        mock_response_final.to_message.return_value = {"role": "assistant", "content": "Sorry."}

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=[mock_response_with_tool, mock_response_final])
        mock_llm.build_tool_result_message = MagicMock(return_value={"role": "tool", "content": "denied", "tool_call_id": "call_1"})

        with patch("opsbot.tools.registry.get_tool_risk", return_value=RiskLevel.WRITE):
            engine = AgentEngine(mcp_manager=mock_mcp, memory=mock_memory)
            engine._llm = mock_llm

            result = await engine.process(
                message="restart checkout deployment",
                channel_id="C1",
                requester_slack_id="U_readonly",
                requester_role="readonly",
            )

        # Should complete without calling the MCP tool
        mock_mcp.call_tool.assert_not_called()
        assert result.status in ("completed", "failed")


class TestDestructiveRaisesNeedsApproval:
    @pytest.mark.asyncio
    async def test_destructive_tool_raises(self):
        mock_mcp = MagicMock()
        mock_mcp.get_all_tools.return_value = []
        mock_memory = AsyncMock()
        mock_memory.get_history.return_value = []
        mock_memory.append_many = AsyncMock()

        tool_call = MagicMock()
        tool_call.name = "k8s_deploy_image"
        tool_call.args = {"deployment": "api", "image": "api:v2"}
        tool_call.id = "call_1"

        mock_response = MagicMock()
        mock_response.tool_calls = [tool_call]
        mock_response.content = None
        mock_response.to_message.return_value = {"role": "assistant", "tool_calls": []}

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=mock_response)

        with patch("opsbot.tools.registry.get_tool_risk", return_value=RiskLevel.DESTRUCTIVE), \
             patch("opsbot.tools.registry.get_human_description", return_value="Deploy api:v2"):
            engine = AgentEngine(mcp_manager=mock_mcp, memory=mock_memory)
            engine._llm = mock_llm

            with pytest.raises(NeedsApprovalError) as exc_info:
                await engine.process(
                    message="deploy api:v2",
                    channel_id="C1",
                    requester_slack_id="U_sre",
                    requester_role="sre",
                )

            assert exc_info.value.tool_name == "k8s_deploy_image"
