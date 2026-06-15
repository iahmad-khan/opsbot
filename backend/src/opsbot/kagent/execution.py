"""
KAGENT execution engine — replaces the Celery process_message_task.

Handles the full lifecycle of a Slack message:
  1. Get/create the user in PostgreSQL
  2. Create a Task record
  3. Route SLO/RCA requests to the SRE modules; everything else goes to KAGENT
  4. Stream progress updates back to Slack via working_ts
  5. Handle approval events (KAGENT pauses → post Slack button → KAGENT resumes)
  6. Finalise Task record and write AuditLog
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

import structlog

from opsbot.integrations.slack.client import SlackClient
from opsbot.integrations.slack.formatters import format_rca_report, format_slo_proposal
from opsbot.kagent import client as kagent_client
from opsbot.models.db import (
    AuditLog,
    Task,
    TaskStatus,
    User,
    UserRole,
    make_session_factory,
)

log = structlog.get_logger(__name__)

_GENERAL_AGENT = "opsbot-general"


async def execute_message(
    *,
    message: str,
    channel_id: str,
    requester_slack_id: str,
    thread_ts: str | None,
    working_ts: str | None,
) -> None:
    """
    Full async handler for a Slack message.  Runs as a background asyncio task.
    Never raises — all errors are caught and posted back to Slack.
    """
    from sqlalchemy import select

    slack = SlackClient()
    session_factory = make_session_factory()
    task_id = None

    try:
        # --- 1. Get or create user ---
        async with session_factory() as db:
            user_result = await db.execute(
                select(User).where(User.slack_user_id == requester_slack_id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                try:
                    user_info = await slack.get_user_info(requester_slack_id)
                except Exception:
                    user_info = {}
                user = User(
                    slack_user_id=requester_slack_id,
                    slack_username=user_info.get("name", requester_slack_id),
                    email=user_info.get("email"),
                    role=UserRole.DEVELOPER,
                )
                db.add(user)
                await db.commit()

        # --- 2. Create Task record ---
        async with session_factory() as db:
            task_record = Task(
                slack_channel_id=channel_id,
                slack_thread_ts=thread_ts,
                requester_slack_id=requester_slack_id,
                original_message=message,
                status=TaskStatus.RUNNING,
            )
            db.add(task_record)
            await db.commit()
            await db.refresh(task_record)
            task_id = task_record.id

        # --- 3. Route request ---
        from opsbot.agent.router import Intent, detect_intent
        intent = detect_intent(message)
        log.info("kagent.intent", task_id=str(task_id), intent=intent.intent)

        if intent.intent == Intent.SLO_ANALYSIS and intent.service_name:
            response_text = await _run_slo(intent.service_name, intent.namespace or "default", working_ts, channel_id, slack)
        elif intent.intent == Intent.RCA:
            response_text = await _run_rca(message, intent.service_name, intent.namespace or "default", working_ts, channel_id, slack)
        else:
            response_text = await _run_kagent(
                message=message,
                channel_id=channel_id,
                thread_ts=thread_ts,
                requester_slack_id=requester_slack_id,
                task_id=str(task_id),
                working_ts=working_ts,
                slack=slack,
            )

        # --- 4. Post final response ---
        if response_text:
            await slack.post_message(channel_id, text=response_text, thread_ts=thread_ts)

        # --- 5. Finalise Task + AuditLog ---
        async with session_factory() as db:
            t = await db.get(Task, task_id)
            if t:
                t.status = TaskStatus.COMPLETED
                t.completed_at = datetime.now(UTC)
                db.add(AuditLog(
                    task_id=task_id,
                    actor_slack_id=requester_slack_id,
                    action="message_processed",
                    success=True,
                ))
                await db.commit()

    except _ApprovalNeededError:
        # Approval buttons already posted by _run_kagent; mark task waiting
        if task_id:
            async with session_factory() as db:
                t = await db.get(Task, task_id)
                if t:
                    t.status = TaskStatus.WAITING_APPROVAL
                    await db.commit()

    except Exception as exc:
        log.error("kagent.execution.failed", task_id=str(task_id) if task_id else None, error=str(exc))
        if task_id:
            async with session_factory() as db:
                t = await db.get(Task, task_id)
                if t:
                    t.status = TaskStatus.FAILED
                    t.error = str(exc)
                    await db.commit()
        import contextlib
        with contextlib.suppress(Exception):
            await slack.post_message(
                channel_id,
                text="❌ I ran into an error processing your request. Please try again or contact your DevOps team.",
                thread_ts=thread_ts,
            )


class _ApprovalNeededError(Exception):
    pass


async def _run_slo(service_name: str, namespace: str, working_ts: str | None, channel_id: str, slack: SlackClient) -> str:
    if working_ts:
        await _safe_update(slack, channel_id, working_ts, f"🔍 Analyzing SLOs for `{service_name}`...")
    from opsbot.sre.slo_analyzer import SLOAnalyzer
    result = await SLOAnalyzer().analyze(service_name=service_name, namespace=namespace)
    return format_slo_proposal(result)


async def _run_rca(message: str, service_name: str | None, namespace: str, working_ts: str | None, channel_id: str, slack: SlackClient) -> str:
    if working_ts:
        await _safe_update(slack, channel_id, working_ts, "🔍 Gathering signals for root cause analysis...")
    from opsbot.sre.rca_engine import RCAEngine
    result = await RCAEngine().analyze(
        incident_description=message,
        service_name=service_name,
        namespace=namespace,
    )
    return format_rca_report(result)


async def _run_kagent(
    *,
    message: str,
    channel_id: str,
    thread_ts: str | None,
    requester_slack_id: str,
    task_id: str,
    working_ts: str | None,
    slack: SlackClient,
) -> str:
    """Call KAGENT via A2A, stream progress, handle approval events."""
    from opsbot.agent.memory import ConversationMemory

    # Fetch Redis conversation context to seed the session
    memory = ConversationMemory()
    prior_context = await memory.get_history(channel_id, thread_ts)

    session_id = f"{channel_id}:{thread_ts or 'dm'}"
    chunks: list[str] = []
    approval_posted = False

    async for event in kagent_client.run_agent(
        agent_name=_GENERAL_AGENT,
        message=message,
        session_id=session_id,
        prior_context=prior_context,
    ):
        if event.type == "text":
            chunks.append(event.text)
            # Streaming progress: update the ack message with accumulated text
            if working_ts and chunks:
                accumulated = "".join(chunks)
                await _safe_update(slack, channel_id, working_ts, accumulated)

        elif event.type == "tool_progress":
            # Per-tool progress update (KAGENT emits these as tools are called)
            tool_display = event.tool_name or "tool"
            if working_ts:
                await _safe_update(slack, channel_id, working_ts, f"🔧 Running `{tool_display}`...")

        elif event.type == "approval_required":
            # KAGENT paused — post our Slack approval button and mark task waiting
            await _handle_kagent_approval(
                event=event,
                channel_id=channel_id,
                thread_ts=thread_ts,
                requester_slack_id=requester_slack_id,
                task_id=task_id,
                slack=slack,
            )
            approval_posted = True

        elif event.type == "error":
            return event.text

    if approval_posted:
        raise _ApprovalNeededError()

    # Persist the exchange in Redis for future context
    try:
        memory = ConversationMemory()
        await memory.append_many(channel_id, [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "".join(chunks)},
        ], thread_ts)
    except Exception as exc:
        log.warning("kagent.memory.save.failed", error=str(exc))

    return "".join(chunks)


async def _handle_kagent_approval(
    *,
    event,
    channel_id: str,
    thread_ts: str | None,
    requester_slack_id: str,
    task_id: str,
    slack: SlackClient,
) -> None:
    """Create an Approval record in PostgreSQL and post a Slack button."""
    from opsbot.models.db import Approval, make_session_factory
    from opsbot.workflows.approval import ApprovalWorkflow
    from opsbot.workflows.notification import build_approval_blocks

    session_factory = make_session_factory()
    approval_wf = ApprovalWorkflow()

    tool_args = dict(event.tool_args or {})
    if event.approval_crd_name:
        tool_args["__kagent_approval_crd__"] = event.approval_crd_name

    async with session_factory() as db:
        from opsbot.models.db import Task
        task_record = await db.get(Task, _uuid.UUID(task_id) if isinstance(task_id, str) else task_id)
        real_task_id = task_record.id if task_record else None

        if real_task_id:
            approval = await approval_wf.create_approval(
                db=db,
                task_id=real_task_id,
                tool_name=event.tool_name or "unknown",
                tool_args=tool_args,
                description=event.description or f"Execute `{event.tool_name}`",
                risk_level=event.risk_level or "DESTRUCTIVE",
                requester_slack_id=requester_slack_id,
                channel_id=channel_id,
            )
            approval_id = approval.id
        else:
            return

    dual = approval_wf.needs_dual_approval(event.tool_name or "")
    async with session_factory() as db:
        approval = await db.get(Approval, approval_id)
        if not approval:
            return
        blocks = build_approval_blocks(approval)

    notice = "⚠️ *Dual approval required* — this operation needs 2 approvers.\n" if dual else ""
    result = await slack.post_message(
        channel_id,
        text=f"{notice}Approval required: {event.description or event.tool_name}",
        blocks=blocks,
        thread_ts=thread_ts,
    )

    async with session_factory() as db:
        a = await db.get(Approval, approval_id)
        if a:
            a.slack_message_ts = result.get("ts")
            await db.commit()


async def _safe_update(slack: SlackClient, channel: str, ts: str, text: str) -> None:
    try:
        await slack.update_message(channel=channel, ts=ts, text=text)
    except Exception as exc:
        log.warning("kagent.progress.update.failed", error=str(exc))


async def execute_approved_tool(
    *,
    approval_id: str,
    approver_slack_id: str,
    approved: bool,
    reason: str = "",
    channel_id: str | None = None,
    thread_ts: str | None = None,
) -> dict:
    """
    Execute or deny an approved tool call.
    Checks if a KAGENT Approval CRD is linked — if so, patches it.
    Otherwise executes directly (for backwards compat with non-KAGENT approvals).
    """
    from opsbot.models.db import AuditLog, Task
    from opsbot.workflows.approval import ApprovalWorkflow

    slack = SlackClient()
    session_factory = make_session_factory()
    approval_wf = ApprovalWorkflow()
    aid = _uuid.UUID(approval_id)

    async with session_factory() as db:
        from opsbot.models.db import Approval, ApprovalStatus
        existing = await db.get(Approval, aid)
        if not existing:
            log.error("kagent.approval.not_found", approval_id=str(aid))
            return {"status": "not_found"}

        if approved:
            # The REST approve route may have already called approve(); skip if so.
            if existing.status == ApprovalStatus.APPROVED:
                approval = existing
            else:
                approval = await approval_wf.approve(db, aid, approver_slack_id)
        else:
            if existing.status == ApprovalStatus.DENIED:
                approval = existing
            else:
                approval = await approval_wf.deny(db, aid, approver_slack_id, reason)

    if not approved:
        if channel_id:
            await slack.post_message(
                channel_id,
                text=f"❌ Operation denied by <@{approver_slack_id}>.",
                thread_ts=thread_ts,
            )
        return {"status": "denied"}

    raw_tool_args = dict(approval.tool_args or {})
    kagent_crd_name: str | None = raw_tool_args.pop("__kagent_approval_crd__", None)

    if kagent_crd_name:
        # Patch the KAGENT Approval CRD — KAGENT will resume the agent
        success = await kagent_client.patch_approval(kagent_crd_name, approved=True, reason="")
        if channel_id:
            status_text = "✅ Approved — KAGENT will resume execution." if success else "❌ Approval patch failed. Check KAGENT logs."
            await slack.post_message(channel_id, text=status_text, thread_ts=thread_ts)

        async with session_factory() as db:
            task = await db.get(Task, approval.task_id)
            if task:
                db.add(AuditLog(
                    task_id=approval.task_id,
                    actor_slack_id=approver_slack_id,
                    action=f"approved:{approval.tool_name}",
                    tool_name=approval.tool_name,
                    tool_args=raw_tool_args,
                    risk_level=approval.risk_level,
                    success=success,
                ))
                await db.commit()

        return {"status": "kagent_resumed" if success else "kagent_patch_failed"}

    # --- Legacy path: no KAGENT CRD, call tool directly via MCP (for local dev) ---
    log.warning("kagent.approval.no_crd", approval_id=approval_id)
    if channel_id:
        await slack.post_message(
            channel_id,
            text="✅ Approved — (KAGENT not configured; tool will execute on next agent run).",
            thread_ts=thread_ts,
        )
    return {"status": "approved_no_kagent"}


async def run_slo_analysis_background(
    *,
    service_name: str,
    namespace: str,
    lookback_days: int,
    requester_slack_id: str,
    channel_id: str,
    thread_ts: str | None = None,
    create_pr: bool = False,
    target_repo: str | None = None,
) -> None:
    """Background task for SLO analysis — replaces the Celery run_slo_analysis_task."""
    slack = SlackClient()
    try:
        from opsbot.integrations.slack.formatters import format_slo_proposal
        from opsbot.sre.slo_analyzer import SLOAnalyzer

        result = await SLOAnalyzer().analyze(
            service_name=service_name,
            namespace=namespace,
            lookback_days=lookback_days,
        )
        report = format_slo_proposal(result)
        await slack.post_message(channel_id, text=report, thread_ts=thread_ts)

        if create_pr and target_repo and result.get("slo_yaml"):
            from opsbot.sre.fix_generator import FixGenerator
            pr_result = await FixGenerator().generate_fix(
                issue_description=f"Add SLO rules for {service_name}",
                root_cause="SLO configuration missing",
                affected_files=[{"path": f"monitoring/slos/{service_name}.yaml", "description": "SLO PrometheusRule"}],
                repo=target_repo,
                auto_create_pr=True,
                requester_slack_id=requester_slack_id,
            )
            if pr_result.get("pr_url"):
                await slack.post_message(channel_id, text=f"📎 PR created: {pr_result['pr_url']}", thread_ts=thread_ts)
    except Exception as exc:
        log.error("slo_analysis.failed", service=service_name, error=str(exc))
        await slack.post_message(
            channel_id,
            text=f"❌ SLO analysis failed for `{service_name}`: {exc}",
            thread_ts=thread_ts,
        )


async def expire_approvals_background() -> int:
    """Periodic task: expire timed-out approvals. Called by a K8s CronJob HTTP trigger."""
    from opsbot.workflows.approval import ApprovalWorkflow
    session_factory = make_session_factory()
    async with session_factory() as db:
        count = await ApprovalWorkflow().expire_old_approvals(db)
    if count:
        log.info("approvals.expired", count=count)
    return count


async def purge_audit_logs_background() -> int:
    """Periodic task: purge old audit log rows. Called by a K8s CronJob HTTP trigger."""
    from datetime import timedelta

    from sqlalchemy import delete

    from opsbot.config.settings import get_settings
    from opsbot.models.db import AuditLog

    s = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=s.audit_log_retention_days)
    session_factory = make_session_factory()
    async with session_factory() as db:
        result = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
        deleted = result.rowcount
        await db.commit()
    if deleted:
        log.info("audit_logs.purged", count=deleted)
    return deleted
