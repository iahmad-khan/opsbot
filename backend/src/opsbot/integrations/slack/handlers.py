from __future__ import annotations

import re
import uuid
from typing import Any

import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from opsbot.config.settings import get_settings
from opsbot.integrations.slack.client import SlackClient
from opsbot.integrations.slack.formatters import format_agent_response, format_error
from opsbot.workflows.notification import build_approval_blocks, build_approval_resolved_blocks, build_task_status_blocks

log = structlog.get_logger(__name__)

# Late imports to avoid circular deps
_bolt_app: AsyncApp | None = None
_socket_handler: AsyncSocketModeHandler | None = None


def get_bolt_app() -> AsyncApp:
    global _bolt_app
    if _bolt_app is None:
        s = get_settings()
        _bolt_app = AsyncApp(
            token=s.slack_bot_token,
            signing_secret=s.slack_signing_secret,
        )
        _register_handlers(_bolt_app)
    return _bolt_app


def _register_handlers(app: AsyncApp) -> None:
    @app.event("app_mention")
    async def handle_mention(event: dict, say, client) -> None:
        await _handle_message_event(event, say, client)

    @app.event("message")
    async def handle_dm(event: dict, say, client) -> None:
        # Only handle DMs (channel_type == "im")
        if event.get("channel_type") == "im" and not event.get("bot_id"):
            await _handle_message_event(event, say, client)

    @app.action("approval_approve")
    async def handle_approve(ack, body, client) -> None:
        await ack()
        await _handle_approval_action(body, client, approved=True)

    @app.action("approval_deny")
    async def handle_deny(ack, body, client) -> None:
        await ack()
        approval_id = body["actions"][0]["value"]
        reason = ""  # Could open a modal to collect reason
        await _handle_approval_action(body, client, approved=False, reason=reason)

    @app.command("/opsbot")
    async def handle_slash(ack, body, say) -> None:
        await ack()
        subcommand = body.get("text", "help").strip().lower()
        if subcommand == "help":
            await say(text=_help_text())
        elif subcommand == "status":
            await _handle_status(body, say)
        elif subcommand.startswith("rbac"):
            await _handle_rbac(body, say)
        else:
            await say(text=f"Unknown subcommand: `{subcommand}`. Try `/opsbot help`")


async def _handle_message_event(event: dict, say, client) -> None:
    # Strip the bot mention prefix
    text = event.get("text", "")
    bot_user_id_pattern = r"<@[A-Z0-9]+>"
    text = re.sub(bot_user_id_pattern, "", text).strip()

    if not text:
        await say(text="Hi! How can I help? Try asking me to check pod logs, deploy a service, or run an RCA.")
        return

    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    requester_slack_id = event.get("user")

    # Acknowledge receipt immediately
    await say(
        text="⏳ Working on it...",
        thread_ts=thread_ts,
    )

    # Dispatch to Celery (keeps Slack's 3s timeout happy)
    from opsbot.tasks.celery_app import process_message_task
    process_message_task.delay(
        message=text,
        channel_id=channel_id,
        requester_slack_id=requester_slack_id,
        thread_ts=thread_ts,
    )


async def _handle_approval_action(body: dict, client, approved: bool, reason: str = "") -> None:
    action = body["actions"][0]
    approval_id_str = action["value"]
    approver_slack_id = body["user"]["id"]
    channel_id = body["container"]["channel_id"]
    message_ts = body["container"]["message_ts"]

    try:
        approval_id = uuid.UUID(approval_id_str)
    except ValueError:
        log.error("approval.invalid_id", value=approval_id_str)
        return

    # Update Slack message immediately to show it's been processed
    slack = SlackClient()
    if approved:
        await slack.update_message(
            channel=channel_id,
            ts=message_ts,
            text=f"✅ Approved by <@{approver_slack_id}>",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"✅ *Approved* by <@{approver_slack_id}> — executing..."}
            }],
        )
    else:
        await slack.update_message(
            channel=channel_id,
            ts=message_ts,
            text=f"❌ Denied by <@{approver_slack_id}>",
            blocks=[{
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"❌ *Denied* by <@{approver_slack_id}>"}
            }],
        )

    from opsbot.tasks.celery_app import process_approval_task
    process_approval_task.delay(
        approval_id=str(approval_id),
        approver_slack_id=approver_slack_id,
        approved=approved,
        reason=reason,
        channel_id=channel_id,
        thread_ts=body.get("message", {}).get("thread_ts"),
    )


async def _handle_status(body: dict, say) -> None:
    from opsbot.mcp.manager import get_manager
    manager = get_manager()
    server_status = manager.get_server_status()
    lines = ["*OpsBot Status*", ""]
    for server, status in server_status.items():
        emoji = "🟢" if status == "connected" else "🔴"
        lines.append(f"{emoji} `{server}`: {status}")
    await say(text="\n".join(lines))


async def _handle_rbac(body: dict, say) -> None:
    text = body.get("text", "").strip()
    parts = text.split()
    if len(parts) < 3 or parts[0] != "rbac":
        await say(text="Usage: `/opsbot rbac add @user <role>` or `/opsbot rbac list`\nRoles: `admin`, `sre`, `developer`, `readonly`")
        return
    await say(text="RBAC management via slash command — use the web dashboard for full RBAC control.")


def _help_text() -> str:
    return """\
*OpsBot Help* 🤖

I'm your AI-powered DevOps & SRE assistant. Just ask me naturally:

*Kubernetes*
• `@opsbot list pods in namespace default`
• `@opsbot check logs of payment-service`
• `@opsbot deploy tag v1.2.3 to uat`
• `@opsbot rollback checkout-service in production`
• `@opsbot scale payment-api to 5 replicas`

*GitHub*
• `@opsbot add @john to repo backend-api with push access`
• `@opsbot list open PRs in frontend repo`

*ArgoCD*
• `@opsbot sync payment-service in argocd`
• `@opsbot rollback checkout-app to previous version`

*Terraform*
• `@opsbot run terraform plan in production workspace`
• `@opsbot apply terraform in staging`

*SRE Intelligence*
• `@opsbot analyze checkout-service and propose SLOs`
• `@opsbot investigate the 5xx spike in payment-service over the last 2 hours`

*Slash Commands*
• `/opsbot help` — this message
• `/opsbot status` — check MCP server connections
• `/opsbot rbac add @user sre` — manage RBAC

*Approval Flow*: Destructive operations require approval. I'll send a button — any admin or SRE can approve.
"""


async def start_socket_mode() -> None:
    s = get_settings()
    app = get_bolt_app()
    handler = AsyncSocketModeHandler(app, s.slack_app_token)
    await handler.start_async()
