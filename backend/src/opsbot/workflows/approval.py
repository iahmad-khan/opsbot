from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opsbot.config.settings import get_settings
from opsbot.models.db import Approval, ApprovalStatus, AuditLog, Task, TaskStatus

log = structlog.get_logger(__name__)


class ApprovalWorkflow:
    async def create_approval(
        self,
        db: AsyncSession,
        task_id: uuid.UUID,
        tool_name: str,
        tool_args: dict,
        description: str,
        risk_level: str,
        requester_slack_id: str,
        channel_id: str | None = None,
    ) -> Approval:
        s = get_settings()
        expires_at = datetime.now(UTC) + timedelta(minutes=s.approval_timeout_minutes)

        approval = Approval(
            task_id=task_id,
            status=ApprovalStatus.PENDING,
            risk_level=risk_level,
            tool_name=tool_name,
            tool_args=tool_args,
            description=description,
            requester_slack_id=requester_slack_id,
            slack_channel_id=channel_id,
            expires_at=expires_at,
        )
        db.add(approval)

        # Update task status
        task = await db.get(Task, task_id)
        if task:
            task.status = TaskStatus.WAITING_APPROVAL

        await db.commit()
        await db.refresh(approval)
        log.info("approval.created", approval_id=str(approval.id), tool=tool_name, risk=risk_level)
        return approval

    async def approve(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        approver_slack_id: str,
    ) -> Approval:
        # SELECT FOR UPDATE prevents two concurrent approvers from both passing the
        # status check and triggering double-execution.
        result = await db.execute(
            select(Approval).where(Approval.id == approval_id).with_for_update()
        )
        approval = result.scalar_one_or_none()
        if not approval:
            raise ValueError(f"Approval {approval_id} not found")
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval is already {approval.status}")
        if approval.expires_at and datetime.now(UTC) > approval.expires_at:
            approval.status = ApprovalStatus.TIMED_OUT
            await db.commit()
            raise ValueError("Approval has expired")

        # Verify the approver has the required role (admin or sre)
        from opsbot.models.db import User
        user_result = await db.execute(select(User).where(User.slack_user_id == approver_slack_id))
        approver_user = user_result.scalar_one_or_none()
        approver_role = approver_user.role if approver_user else "developer"
        if not self.can_approve(approver_role, approval.risk_level):
            raise ValueError(
                f"User {approver_slack_id} (role: {approver_role}) does not have permission "
                f"to approve {approval.risk_level} operations. Required role: admin or sre."
            )

        approval.status = ApprovalStatus.APPROVED
        approval.approver_slack_id = approver_slack_id
        approval.resolved_at = datetime.now(UTC)

        task = await db.get(Task, approval.task_id)
        if task:
            task.status = TaskStatus.APPROVED

        # Audit log
        db.add(AuditLog(
            task_id=approval.task_id,
            actor_slack_id=approver_slack_id,
            action=f"approved:{approval.tool_name}",
            tool_name=approval.tool_name,
            tool_args=approval.tool_args,
            risk_level=approval.risk_level,
            success=True,
        ))

        await db.commit()
        await db.refresh(approval)
        log.info("approval.approved", approval_id=str(approval_id), approver=approver_slack_id)
        return approval

    async def deny(
        self,
        db: AsyncSession,
        approval_id: uuid.UUID,
        denier_slack_id: str,
        reason: str = "",
    ) -> Approval:
        result = await db.execute(
            select(Approval).where(Approval.id == approval_id).with_for_update()
        )
        approval = result.scalar_one_or_none()
        if not approval:
            raise ValueError(f"Approval {approval_id} not found")
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval is already {approval.status}")

        approval.status = ApprovalStatus.DENIED
        approval.approver_slack_id = denier_slack_id
        approval.denial_reason = reason
        approval.resolved_at = datetime.now(UTC)

        task = await db.get(Task, approval.task_id)
        if task:
            task.status = TaskStatus.DENIED

        db.add(AuditLog(
            task_id=approval.task_id,
            actor_slack_id=denier_slack_id,
            action=f"denied:{approval.tool_name}",
            tool_name=approval.tool_name,
            tool_args=approval.tool_args,
            risk_level=approval.risk_level,
            success=False,
            result_summary=f"Denied: {reason}",
        ))

        await db.commit()
        await db.refresh(approval)
        log.info("approval.denied", approval_id=str(approval_id), denier=denier_slack_id)
        return approval

    async def get_pending_approvals(self, db: AsyncSession) -> list[Approval]:
        result = await db.execute(
            select(Approval)
            .where(Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.desc())
        )
        return list(result.scalars().all())

    async def expire_old_approvals(self, db: AsyncSession) -> int:
        now = datetime.now(UTC)
        result = await db.execute(
            select(Approval).where(
                Approval.status == ApprovalStatus.PENDING,
                Approval.expires_at < now,
            )
        )
        expired = list(result.scalars().all())
        for approval in expired:
            approval.status = ApprovalStatus.TIMED_OUT
            approval.resolved_at = now
            task = await db.get(Task, approval.task_id)
            if task:
                task.status = TaskStatus.TIMED_OUT
        await db.commit()
        return len(expired)

    def can_approve(self, approver_role: str, risk_level: str) -> bool:
        """Check if a user with the given role can approve this risk level."""
        from opsbot.models.db import UserRole
        return approver_role in (UserRole.ADMIN, UserRole.SRE)

    def needs_dual_approval(self, tool_name: str) -> bool:
        s = get_settings()
        base = tool_name.split("__")[-1] if "__" in tool_name else tool_name
        return base in s.require_dual_approval_for or tool_name in s.require_dual_approval_for
