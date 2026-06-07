from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsbot.models.db import Approval, ApprovalStatus, make_session_factory
from opsbot.models.schemas import ApprovalDecision, ApprovalListResponse, ApprovalRead
from opsbot.workflows.approval import ApprovalWorkflow

router = APIRouter(prefix="/approvals", tags=["approvals"])

_workflow = ApprovalWorkflow()


async def get_db():
    factory = make_session_factory()
    async with factory() as session:
        yield session


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
    try:
        approval = await _workflow.approve(db, approval_id, body.approver_slack_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Trigger execution via Celery
    from opsbot.tasks.celery_app import process_approval_task
    process_approval_task.delay(
        approval_id=str(approval_id),
        approver_slack_id=body.approver_slack_id,
        approved=True,
        channel_id=approval.slack_channel_id,
    )
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
    return ApprovalRead.model_validate(approval)
