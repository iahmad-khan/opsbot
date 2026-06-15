"""Pydantic models for the KAGENT A2A (Agent-to-Agent) protocol."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class A2AMessagePart(BaseModel):
    """A single content part inside an A2A message."""
    kind: str = "text"
    text: str = ""


class A2AMessage(BaseModel):
    """A2A JSON-RPC message object."""
    role: str
    parts: list[A2AMessagePart] = Field(default_factory=list)

    @classmethod
    def user(cls, text: str) -> A2AMessage:
        return cls(role="user", parts=[A2AMessagePart(text=text)])


class A2ARunParams(BaseModel):
    """Parameters for a message/send JSON-RPC call."""
    model_config = ConfigDict(populate_by_name=True)

    message: A2AMessage
    session_id: str = Field(alias="sessionId")
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2ARequest(BaseModel):
    """JSON-RPC 2.0 request envelope for KAGENT A2A."""
    jsonrpc: str = "2.0"
    id: str = "1"
    method: str = "message/send"
    params: A2ARunParams


class A2ARunEvent(BaseModel):
    """A single SSE event line from the KAGENT A2A stream."""
    type: str = "text"
    text: str = ""
    approval_id: str | None = None
    approval_crd_name: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    risk_level: str | None = None
    description: str | None = None
    final: bool = False


class KagentApproval(BaseModel):
    """Represents a KAGENT Approval CRD (simplified for our watcher)."""
    name: str
    namespace: str
    agent_name: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "DESTRUCTIVE"
    description: str = ""
    requester_slack_id: str = ""
    channel_id: str = ""
    thread_ts: str | None = None
    task_id: str | None = None
    slack_message_ts: str | None = None
