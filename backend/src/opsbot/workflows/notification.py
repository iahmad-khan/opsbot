from __future__ import annotations

import uuid
from datetime import UTC

from opsbot.models.db import Approval, RiskLevel

RISK_EMOJIS = {
    RiskLevel.READ: "📖",
    RiskLevel.WRITE: "✏️",
    RiskLevel.DESTRUCTIVE: "⚠️",
}

RISK_COLORS = {
    RiskLevel.READ: "#36a64f",
    RiskLevel.WRITE: "#f0a500",
    RiskLevel.DESTRUCTIVE: "#e01e5a",
}


def build_approval_blocks(approval: Approval, requester_name: str = "") -> list[dict]:
    """Build Slack Block Kit blocks for an approval request."""
    risk = approval.risk_level
    emoji = RISK_EMOJIS.get(risk, "❓")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Approval Required",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Requested by:*\n<@{approval.requester_slack_id}>"},
                {"type": "mrkdwn", "text": f"*Risk Level:*\n`{risk}`"},
                {"type": "mrkdwn", "text": f"*Operation:*\n`{approval.tool_name}`"},
                {
                    "type": "mrkdwn",
                    "text": f"*Expires in:*\n{_format_expires(approval)}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Description:*\n{approval.description}",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                    "style": "primary",
                    "action_id": "approval_approve",
                    "value": str(approval.id),
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Are you sure?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": f"This will execute: *{approval.description}*\n\nThis action cannot be undone.",
                        },
                        "confirm": {"type": "plain_text", "text": "Yes, approve"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Deny", "emoji": True},
                    "style": "danger",
                    "action_id": "approval_deny",
                    "value": str(approval.id),
                },
            ],
        },
    ]
    return blocks


def build_approval_resolved_blocks(
    approval: Approval,
    approver_slack_id: str,
    approved: bool,
    reason: str = "",
) -> list[dict]:
    emoji = "✅" if approved else "❌"
    action = "Approved" if approved else "Denied"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{action}* by <@{approver_slack_id}>\n"
                        f"Operation: `{approval.tool_name}`\n"
                        f"Description: {approval.description}"
                        + (f"\nReason: {reason}" if reason else ""),
            },
        }
    ]


def build_task_status_blocks(
    task_id: uuid.UUID,
    status: str,
    message: str,
    tool_name: str | None = None,
) -> list[dict]:
    status_emojis = {
        "completed": "✅",
        "failed": "❌",
        "running": "⏳",
        "waiting_approval": "⏸️",
    }
    emoji = status_emojis.get(status, "ℹ️")
    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{status.replace('_', ' ').title()}*\n{message}",
            },
        }
    ]
    if tool_name:
        blocks[0]["accessory"] = {
            "type": "overflow",
            "options": [
                {"text": {"type": "plain_text", "text": "View task"}, "value": f"task:{task_id}"}
            ],
            "action_id": "task_overflow",
        }
    return blocks


def build_sre_report_blocks(title: str, content: str, pr_url: str | None = None) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🔬 {title}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": content[:2900]}},
    ]
    if pr_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View PR on GitHub", "emoji": True},
                    "url": pr_url,
                    "action_id": "open_pr",
                }
            ],
        })
    return blocks


def _format_expires(approval: Approval) -> str:
    if not approval.expires_at:
        return "Never"
    from datetime import datetime
    remaining = approval.expires_at - datetime.now(UTC)
    minutes = int(remaining.total_seconds() / 60)
    if minutes <= 0:
        return "Expired"
    return f"{minutes} min"
