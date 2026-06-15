from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsbot.models.db import Approval, ApprovalStatus, make_session_factory
from opsbot.models.schemas import ApprovalDecision, ApprovalListResponse, ApprovalRead
from opsbot.workflows.approval import ApprovalWorkflow

router = APIRouter(prefix="/approvals", tags=["approvals"])

_workflow = ApprovalWorkflow()
log = structlog.get_logger(__name__)


async def get_db():
    factory = make_session_factory()
    async with factory() as session:
        yield session


async def _require_internal_auth(x_internal_token: str | None = Header(None)) -> None:
    """Guard for maintenance endpoints called by in-cluster CronJobs."""
    from opsbot.config.settings import get_settings
    s = get_settings()
    if not x_internal_token or x_internal_token != s.secret_key:
        raise HTTPException(status_code=403, detail="Forbidden")


def _log_bg_error(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception():
        log.error("approval.bg_task.failed", error=str(task.exception()))


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    status: ApprovalStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ApprovalListResponse:
    q = select(Approval).order_by(Approval.created_at.desc())
    if status:
        q = q.where(Approval.status == status)

    pending_count_result = await db.execute(
        select(func.count()).where(Approval.status == ApprovalStatus.PENDING)
    )
    pending_count = pending_count_result.scalar() or 0

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar() or 0

    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    approvals = list(result.scalars().all())

    return ApprovalListResponse(
        items=[ApprovalRead.model_validate(a) for a in approvals],
        total=total,
        pending_count=pending_count,
    )


@router.get("/{approval_id}", response_model=ApprovalRead)
async def get_approval(approval_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ApprovalRead:
    approval = await db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return ApprovalRead.model_validate(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalRead)
async def approve(
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRead:
    """
    Approve a pending operation.

    Workflow:
      1. ApprovalWorkflow.approve() validates RBAC + freeze window → updates DB record
      2. Fire-and-forget task patches KAGENT CRD (skips re-approve since status is already APPROVED)
      3. Write AuditLog
    """
    try:
        approval = await _workflow.approve(db, approval_id, body.approver_slack_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Fire-and-forget: patch KAGENT CRD if present, then post Slack confirmation.
    # execute_approved_tool checks existing status and skips re-approving if already APPROVED.
    from opsbot.kagent.execution import execute_approved_tool
    t = asyncio.create_task(execute_approved_tool(
        approval_id=str(approval_id),
        approver_slack_id=body.approver_slack_id,
        approved=True,
        channel_id=getattr(approval, "slack_channel_id", None),
    ))
    t.add_done_callback(_log_bg_error)

    return ApprovalRead.model_validate(approval)


@router.post("/{approval_id}/deny", response_model=ApprovalRead)
async def deny(
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRead:
    try:
        approval = await _workflow.deny(db, approval_id, body.approver_slack_id, body.denial_reason or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Notify the requester via Slack (mirrors the Slack button handler path)
    from opsbot.kagent.execution import execute_approved_tool
    t = asyncio.create_task(execute_approved_tool(
        approval_id=str(approval_id),
        approver_slack_id=body.approver_slack_id,
        approved=False,
        reason=body.denial_reason or "",
        channel_id=getattr(approval, "slack_channel_id", None),
    ))
    t.add_done_callback(_log_bg_error)

    return ApprovalRead.model_validate(approval)


@router.post("/maintenance/expire", tags=["maintenance"])
async def expire_approvals(_: None = Depends(_require_internal_auth)) -> dict:
    """Expire timed-out pending approvals. Called by the K8s expire-approvals CronJob."""
    from opsbot.kagent.execution import expire_approvals_background
    count = await expire_approvals_background()
    return {"expired": count}


@router.post("/maintenance/purge-audit-logs", tags=["maintenance"])
async def purge_audit_logs(_: None = Depends(_require_internal_auth)) -> dict:
    """Purge audit log rows older than retention window. Called by the K8s purge-audit CronJob."""
    from opsbot.kagent.execution import purge_audit_logs_background
    deleted = await purge_audit_logs_background()
    return {"deleted": deleted}
