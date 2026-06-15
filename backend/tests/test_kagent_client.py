"""Tests for the KAGENT A2A client — schema parsing and event handling."""
from __future__ import annotations

from opsbot.kagent.schemas import A2AMessage, A2ARunEvent


class TestA2AMessage:
    def test_user_factory(self):
        msg = A2AMessage.user("deploy checkout:v2")
        assert msg.role == "user"
        assert msg.parts[0].text == "deploy checkout:v2"

    def test_parts_default_empty(self):
        msg = A2AMessage(role="assistant")
        assert msg.parts == []


class TestA2ARunEvent:
    def test_text_event(self):
        ev = A2ARunEvent(type="text", text="Deployment complete.")
        assert ev.type == "text"
        assert ev.text == "Deployment complete."
        assert ev.final is False

    def test_approval_required_event(self):
        ev = A2ARunEvent(
            type="approval_required",
            tool_name="k8s_deploy_image",
            tool_args={"image": "checkout:v2.0.0", "deployment": "checkout"},
            risk_level="DESTRUCTIVE",
            approval_crd_name="approval-abc123",
            description="Deploy checkout:v2.0.0",
        )
        assert ev.type == "approval_required"
        assert ev.approval_crd_name == "approval-abc123"
        assert ev.tool_args == {"image": "checkout:v2.0.0", "deployment": "checkout"}

    def test_error_event_is_not_final_by_default(self):
        ev = A2ARunEvent(type="error", text="Connection refused")
        assert ev.final is False

    def test_final_event(self):
        ev = A2ARunEvent(type="text", text="Done.", final=True)
        assert ev.final is True

    def test_optional_fields_default_to_none(self):
        ev = A2ARunEvent(type="text", text="ok")
        assert ev.approval_id is None
        assert ev.approval_crd_name is None
        assert ev.tool_name is None
        assert ev.tool_args is None
