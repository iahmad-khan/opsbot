"""Tests for the approval workflow state machine."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opsbot.models.db import Approval, ApprovalStatus, Task, TaskStatus, UserRole
from opsbot.workflows.approval import ApprovalWorkflow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_task() -> Task:
    t = Task()
    t.id = uuid.uuid4()
    t.slack_channel_id = "C123"
    t.requester_slack_id = "U_dev"
    t.original_message = "test"
    t.status = TaskStatus.WAITING_APPROVAL
    return t


def _make_approval(task: Task, risk_level: str = "DESTRUCTIVE") -> Approval:
    a = Approval()
    a.id = uuid.uuid4()
    a.task_id = task.id
    a.status = ApprovalStatus.PENDING
    a.risk_level = risk_level
    a.tool_name = "k8s_deploy_image"
    a.tool_args = {"deployment": "checkout", "image": "checkout:v2.0.0"}
    a.description = "Deploy checkout:v2.0.0"
    a.requester_slack_id = "U_dev"
    a.expires_at = datetime.now(UTC) + timedelta(minutes=30)
    return a


def _make_user(slack_id: str, role: str) -> MagicMock:
    u = MagicMock()
    u.slack_user_id = slack_id
    u.role = role
    return u


def _execute_side_effect(*return_values):
    """Build an AsyncMock that returns a scalar-result mock for each call in order."""
    mocks = []
    for val in return_values:
        m = MagicMock()
        m.scalar_one_or_none.return_value = val
        mocks.append(m)
    return AsyncMock(side_effect=mocks)


# ---------------------------------------------------------------------------
# can_approve() — role check logic
# ---------------------------------------------------------------------------

class TestCanApprove:
    def test_admin_can_approve(self):
        wf = ApprovalWorkflow()
        assert wf.can_approve(UserRole.ADMIN, "DESTRUCTIVE") is True

    def test_sre_can_approve(self):
        wf = ApprovalWorkflow()
        assert wf.can_approve(UserRole.SRE, "DESTRUCTIVE") is True

    def test_developer_cannot_approve(self):
        wf = ApprovalWorkflow()
        assert wf.can_approve(UserRole.DEVELOPER, "DESTRUCTIVE") is False

    def test_readonly_cannot_approve(self):
        wf = ApprovalWorkflow()
        assert wf.can_approve(UserRole.READONLY, "DESTRUCTIVE") is False


# ---------------------------------------------------------------------------
# needs_dual_approval()
# ---------------------------------------------------------------------------

class TestNeedsDualApproval:
    def test_delete_namespace_needs_dual(self):
        with patch("opsbot.workflows.approval.get_settings") as mock_settings:
            mock_settings.return_value.require_dual_approval_for = ["delete_namespace", "drop_database"]
            wf = ApprovalWorkflow()
            assert wf.needs_dual_approval("delete_namespace") is True

    def test_deploy_does_not_need_dual(self):
        with patch("opsbot.workflows.approval.get_settings") as mock_settings:
            mock_settings.return_value.require_dual_approval_for = ["delete_namespace"]
            wf = ApprovalWorkflow()
            assert wf.needs_dual_approval("k8s_deploy_image") is False


# ---------------------------------------------------------------------------
# approve() — enforces RBAC and expires correctly
# ---------------------------------------------------------------------------

class TestApprove:
    @pytest.mark.asyncio
    async def test_admin_can_approve_successfully(self):
        wf = ApprovalWorkflow()
        task = _make_task()
        approval = _make_approval(task)
        admin_user = _make_user("U_admin", UserRole.ADMIN)

        db = AsyncMock()
        # First execute: SELECT FOR UPDATE for Approval
        # Second execute: SELECT User for RBAC check
        db.execute = _execute_side_effect(approval, admin_user)
        db.get = AsyncMock(return_value=task)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await wf.approve(db, approval.id, "U_admin")
        assert result.status == ApprovalStatus.APPROVED
        assert result.approver_slack_id == "U_admin"

    @pytest.mark.asyncio
    async def test_developer_cannot_approve(self):
        wf = ApprovalWorkflow()
        task = _make_task()
        approval = _make_approval(task)
        # Use a *different* developer (not the requester) so the self-approval guard
        # doesn't fire before the role check — we're testing the role check here.
        dev_user2 = _make_user("U_dev2", UserRole.DEVELOPER)

        db = AsyncMock()
        db.execute = _execute_side_effect(approval, dev_user2)

        with pytest.raises(ValueError, match="does not have permission"):
            await wf.approve(db, approval.id, "U_dev2")

    @pytest.mark.asyncio
    async def test_self_approval_raises(self):
        """Requester cannot approve their own operation."""
        wf = ApprovalWorkflow()
        task = _make_task()
        approval = _make_approval(task)  # requester_slack_id = "U_dev"

        db = AsyncMock()
        db.execute = _execute_side_effect(approval)

        with pytest.raises(ValueError, match="cannot approve your own request"):
            await wf.approve(db, approval.id, "U_dev")

    @pytest.mark.asyncio
    async def test_expired_approval_raises(self):
        wf = ApprovalWorkflow()
        task = _make_task()
        approval = _make_approval(task)
        approval.expires_at = datetime.now(UTC) - timedelta(minutes=1)  # already expired

        db = AsyncMock()
        db.execute = _execute_side_effect(approval)
        db.commit = AsyncMock()

        with pytest.raises(ValueError, match="expired"):
            await wf.approve(db, approval.id, "U_admin")

    @pytest.mark.asyncio
    async def test_already_approved_raises(self):
        wf = ApprovalWorkflow()
        task = _make_task()
        approval = _make_approval(task)
        approval.status = ApprovalStatus.APPROVED

        db = AsyncMock()
        db.execute = _execute_side_effect(approval)

        with pytest.raises(ValueError, match="already"):
            await wf.approve(db, approval.id, "U_admin")


# ---------------------------------------------------------------------------
# deny()
# ---------------------------------------------------------------------------

class TestDeny:
    @pytest.mark.asyncio
    async def test_deny_sets_status(self):
        wf = ApprovalWorkflow()
        task = _make_task()
        approval = _make_approval(task)

        db = AsyncMock()
        db.execute = _execute_side_effect(approval)
        db.get = AsyncMock(return_value=task)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        result = await wf.deny(db, approval.id, "U_sre", "Too risky right now")
        assert result.status == ApprovalStatus.DENIED
        assert result.denial_reason == "Too risky right now"


# ---------------------------------------------------------------------------
# expire_old_approvals()
# ---------------------------------------------------------------------------

class TestExpireApprovals:
    @pytest.mark.asyncio
    async def test_expires_timed_out_approvals(self):
        wf = ApprovalWorkflow()
        task = _make_task()
        approval = _make_approval(task)
        approval.expires_at = datetime.now(UTC) - timedelta(minutes=5)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [approval]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.get.return_value = task
        db.commit = AsyncMock()

        count = await wf.expire_old_approvals(db)
        assert count == 1
        assert approval.status == ApprovalStatus.TIMED_OUT
