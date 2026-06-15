"""Initial schema — all tables

Revision ID: 0001
Revises:
Create Date: 2026-06-07
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("slack_user_id", sa.String(64), nullable=False, unique=True),
        sa.Column("slack_username", sa.String(128), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="developer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_slack_user_id", "users", ["slack_user_id"])

    op.create_table(
        "tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slack_channel_id", sa.String(64), nullable=False),
        sa.Column("slack_thread_ts", sa.String(64), nullable=True),
        sa.Column("slack_message_ts", sa.String(64), nullable=True),
        sa.Column("requester_slack_id", sa.String(64), sa.ForeignKey("users.slack_user_id"), nullable=False),
        sa.Column("original_message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("tool_args", sa.JSON(), nullable=True),
        sa.Column("risk_level", sa.String(32), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.String(256), nullable=True),
        sa.Column("conversation_history", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tasks_slack_channel_id", "tasks", ["slack_channel_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])

    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("risk_level", sa.String(32), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("tool_args", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("requester_slack_id", sa.String(64), nullable=False),
        sa.Column("approver_slack_id", sa.String(64), sa.ForeignKey("users.slack_user_id"), nullable=True),
        sa.Column("slack_message_ts", sa.String(64), nullable=True),
        sa.Column("slack_channel_id", sa.String(64), nullable=True),
        sa.Column("denial_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_status", "approvals", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("actor_slack_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(256), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("tool_args", sa.JSON(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(32), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("environment", sa.String(64), nullable=True),
        sa.Column("service_name", sa.String(256), nullable=True),
        sa.Column("image_tag", sa.String(256), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_actor_slack_id", "audit_logs", ["actor_slack_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_environment", "audit_logs", ["environment"])
    op.create_index("ix_audit_logs_service_name", "audit_logs", ["service_name"])

    op.create_table(
        "slo_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("service_name", sa.String(256), nullable=False),
        sa.Column("namespace", sa.String(128), nullable=True),
        sa.Column("report_data", sa.JSON(), nullable=False),
        sa.Column("slo_yaml", sa.Text(), nullable=True),
        sa.Column("github_pr_url", sa.String(512), nullable=True),
        sa.Column("requester_slack_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_slo_reports_service_name", "slo_reports", ["service_name"])
    op.create_index("ix_slo_reports_created_at", "slo_reports", ["created_at"])

    op.create_table(
        "rca_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_description", sa.Text(), nullable=False),
        sa.Column("service_name", sa.String(256), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("contributing_factors", sa.JSON(), nullable=True),
        sa.Column("remediation_steps", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("github_issue_url", sa.String(512), nullable=True),
        sa.Column("github_pr_url", sa.String(512), nullable=True),
        sa.Column("requester_slack_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rca_reports_created_at", "rca_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("rca_reports")
    op.drop_table("slo_reports")
    op.drop_table("audit_logs")
    op.drop_table("approvals")
    op.drop_table("tasks")
    op.drop_table("users")
