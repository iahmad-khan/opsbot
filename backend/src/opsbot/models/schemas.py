from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from opsbot.models.db import ApprovalStatus, RiskLevel, TaskStatus, UserRole

# ---- User ----

class UserBase(BaseModel):
    slack_user_id: str
    slack_username: str
    email: str | None = None
    role: UserRole = UserRole.DEVELOPER


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    email: str | None = None


class UserRead(UserBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Task ----

class TaskCreate(BaseModel):
    slack_channel_id: str
    slack_thread_ts: str | None = None
    requester_slack_id: str
    original_message: str


class TaskRead(BaseModel):
    id: uuid.UUID
    slack_channel_id: str
    slack_thread_ts: str | None
    requester_slack_id: str
    original_message: str
    status: TaskStatus
    tool_name: str | None
    tool_args: dict | None
    risk_level: str | None
    result: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    items: list[TaskRead]
    total: int
    page: int
    page_size: int


# ---- Approval ----

class ApprovalCreate(BaseModel):
    task_id: uuid.UUID
    risk_level: RiskLevel
    tool_name: str
    tool_args: dict
    description: str
    requester_slack_id: str


class ApprovalRead(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    status: ApprovalStatus
    risk_level: str
    tool_name: str
    tool_args: dict
    description: str
    requester_slack_id: str
    approver_slack_id: str | None
    denial_reason: str | None
    expires_at: datetime | None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    approver_slack_id: str
    denial_reason: str | None = None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalRead]
    total: int
    pending_count: int


# ---- Audit Log ----

class AuditLogRead(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    actor_slack_id: str
    action: str
    tool_name: str | None
    tool_args: dict | None
    result_summary: str | None
    risk_level: str | None
    success: bool
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    total: int


# ---- Slack Events ----

class SlackEvent(BaseModel):
    type: str
    event: dict | None = None
    payload: dict | None = None
    challenge: str | None = None


# ---- SRE ----

class SLOAnalysisRequest(BaseModel):
    service_name: str
    namespace: str = "default"
    lookback_days: int = 30
    requester_slack_id: str
    create_pr: bool = False
    target_repo: str | None = None


class SLOProposal(BaseModel):
    service_name: str
    availability_slo: float
    latency_p99_ms: float
    error_budget_percent: float
    current_error_rate: float
    current_latency_p99_ms: float
    slo_yaml: str
    recommendation_reason: str


class RCARequest(BaseModel):
    incident_description: str
    service_name: str | None = None
    namespace: str = "default"
    start_time: datetime | None = None
    end_time: datetime | None = None
    requester_slack_id: str
    create_issue: bool = False
    create_fix_pr: bool = False
    target_repo: str | None = None


class RCAResult(BaseModel):
    root_cause: str
    confidence: float
    contributing_factors: list[str]
    evidence: dict[str, Any]
    remediation_steps: list[str]
    github_issue_url: str | None = None
    github_pr_url: str | None = None


# ---- Health ----

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    checks: dict[str, str]
    mcp_servers: dict[str, str]
