"""Drop unused conversation_history column from tasks

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-07
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("tasks", "conversation_history")


def downgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("conversation_history", sa.JSON(), nullable=True),
    )
