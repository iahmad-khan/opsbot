from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opsbot.models.db import AuditLog, Task, TaskStatus, make_session_factory
from opsbot.models.schemas import AuditLogListResponse, AuditLogRead, TaskListResponse, TaskRead

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def get_db():
    factory = make_session_factory()
    async with factory() as session:
        yield session


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: TaskStatus | None = None,
    channel_id: str | None = None,
    requester_slack_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    q = select(Task).order_by(Task.created_at.desc())
    if status:
        q = q.where(Task.status == status)
    if channel_id:
        q = q.where(Task.slack_channel_id == channel_id)
    if requester_slack_id:
        q = q.where(Task.requester_slack_id == requester_slack_id)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar() or 0

    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    tasks = list(result.scalars().all())

    return TaskListResponse(
        items=[TaskRead.model_validate(t) for t in tasks],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> TaskRead:
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskRead.model_validate(task)


@router.get("/{task_id}/audit", response_model=AuditLogListResponse)
async def get_task_audit(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> AuditLogListResponse:
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.task_id == task_id)
        .order_by(AuditLog.created_at.asc())
    )
    logs = list(result.scalars().all())
    return AuditLogListResponse(
        items=[AuditLogRead.model_validate(l) for l in logs],
        total=len(logs),
    )


@router.get("/audit/all", response_model=AuditLogListResponse)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    actor_slack_id: str | None = None,
    tool_name: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    if actor_slack_id:
        q = q.where(AuditLog.actor_slack_id == actor_slack_id)
    if tool_name:
        q = q.where(AuditLog.tool_name == tool_name)

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar() or 0
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    logs = list(result.scalars().all())

    return AuditLogListResponse(
        items=[AuditLogRead.model_validate(l) for l in logs],
        total=total,
    )
