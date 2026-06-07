from __future__ import annotations

import asyncio
import uuid
from datetime import UTC

import structlog
from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_init, worker_shutdown

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)

s = get_settings()

celery_app = Celery(
    "opsbot",
    broker=s.celery_broker_url,
    backend=s.celery_result_backend,
    include=["opsbot.tasks.celery_app"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # redbeat uses Redis for distributed beat locking — prevents double-firing on restart
    redbeat_redis_url=s.redis_url,
    task_routes={
        "opsbot.tasks.celery_app.process_message_task": {"queue": "default"},
        "opsbot.tasks.celery_app.process_approval_task": {"queue": "approvals"},
        "opsbot.tasks.celery_app.run_slo_analysis_task": {"queue": "sre"},
        "opsbot.tasks.celery_app.run_rca_task": {"queue": "sre"},
        "opsbot.tasks.celery_app.expire_approvals_task": {"queue": "default"},
        "opsbot.tasks.celery_app.purge_old_audit_logs_task": {"queue": "default"},
    },
    beat_schedule={
        "expire-approvals-every-5min": {
            "task": "opsbot.tasks.celery_app.expire_approvals_task",
            "schedule": crontab(minute="*/5"),
        },
        "purge-audit-logs-daily": {
            "task": "opsbot.tasks.celery_app.purge_old_audit_logs_task",
            "schedule": crontab(hour=2, minute=0),
        },
    },
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


# ---------------------------------------------------------------------------
# Per-worker event-loop and DB connection pool
#
# Creating a new asyncio loop + SQLAlchemy engine per task would open up to
# pool_size connections per task execution, exhausting PostgreSQL's
# max_connections under load.  Instead we create ONE loop and ONE engine per
# worker process via Celery signals, then reuse them for every task.
# ---------------------------------------------------------------------------

_worker_loop: asyncio.AbstractEventLoop | None = None
_session_factory_cache = None


@worker_init.connect
def _setup_worker(**kwargs):
    global _worker_loop, _session_factory_cache
    from opsbot.models.db import make_engine, make_session_factory
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    engine = make_engine()
    _session_factory_cache = make_session_factory(engine)
    log.info("celery.worker.init", loop_id=id(_worker_loop))


@worker_shutdown.connect
def _teardown_worker(**kwargs):
    global _worker_loop
    if _worker_loop and not _worker_loop.is_closed():
        import contextlib
        with contextlib.suppress(Exception):
            _worker_loop.run_until_complete(_worker_loop.shutdown_asyncgens())
        _worker_loop.close()
    log.info("celery.worker.shutdown")


def _get_session_factory():
    """Return the cached session factory, creating it on first call (beat/test contexts)."""
    global _session_factory_cache
    if _session_factory_cache is None:
        from opsbot.models.db import make_session_factory
        _session_factory_cache = make_session_factory()
    return _session_factory_cache


def _run_async(coro):
    """Run a coroutine, reusing the per-worker event loop when inside a worker process."""
    global _worker_loop
    if _worker_loop and not _worker_loop.is_closed():
        return _worker_loop.run_until_complete(coro)
    # Fallback for beat process or direct invocation
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="opsbot.tasks.celery_app.process_message_task", bind=True, max_retries=2)
def process_message_task(
    self,
    message: str,
    channel_id: str,
    requester_slack_id: str,
    thread_ts: str | None = None,
    working_ts: str | None = None,
) -> dict:
    return _run_async(_process_message(self, message, channel_id, requester_slack_id, thread_ts, working_ts))


async def _process_message(task, message: str, channel_id: str, requester_slack_id: str, thread_ts: str | None, working_ts: str | None = None) -> dict:
    import structlog
    structlog.contextvars.bind_contextvars(celery_task_id=task.request.id, user=requester_slack_id)
    from sqlalchemy import select as sa_select

    from opsbot.agent.engine import AgentEngine, NeedsApprovalError
    from opsbot.agent.router import Intent, detect_intent
    from opsbot.integrations.slack.client import SlackClient
    from opsbot.integrations.slack.formatters import (
        format_rca_report,
        format_slo_proposal,
    )
    from opsbot.models.db import AuditLog, Task, TaskStatus, User, UserRole
    from opsbot.workflows.approval import ApprovalWorkflow
    from opsbot.workflows.notification import build_approval_blocks

    slack = SlackClient()
    session_factory = _get_session_factory()

    # Get or create user
    async with session_factory() as db:
        user_result = await db.execute(
            sa_select(User).where(User.slack_user_id == requester_slack_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            user_info = await slack.get_user_info(requester_slack_id)
            user = User(
                slack_user_id=requester_slack_id,
                slack_username=user_info.get("name", requester_slack_id),
                email=user_info.get("email"),
                role=UserRole.DEVELOPER,
            )
            db.add(user)
            await db.commit()

        # Create task record
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

    intent = detect_intent(message)
    log.info("task.intent", task_id=str(task_id), intent=intent.intent, service=intent.service_name)

    try:
        # Route to SRE modules or general agent
        if intent.intent == Intent.SLO_ANALYSIS and intent.service_name:
            from opsbot.sre.slo_analyzer import SLOAnalyzer
            analyzer = SLOAnalyzer()
            result = await analyzer.analyze(
                service_name=intent.service_name,
                namespace=intent.namespace or "default",
            )
            response_text = format_slo_proposal(result)
            await slack.post_message(channel_id, text=response_text, thread_ts=thread_ts)

        elif intent.intent == Intent.RCA:
            from opsbot.sre.rca_engine import RCAEngine
            engine_rca = RCAEngine()
            result = await engine_rca.analyze(
                incident_description=message,
                service_name=intent.service_name,
                namespace=intent.namespace or "default",
            )
            response_text = format_rca_report(result)
            await slack.post_message(channel_id, text=response_text, thread_ts=thread_ts)

        else:
            # General ops agent
            # Build a progress callback that keeps the "⏳" Slack message live
            # during long tool chains so users aren't left in silence.
            async def _progress_callback(text: str) -> None:
                if working_ts:
                    try:
                        await slack.update_message(channel=channel_id, ts=working_ts, text=text)
                    except Exception as _exc:
                        log.warning("slack.progress.update.failed", error=str(_exc))

            engine = AgentEngine()
            result_obj = await engine.process(
                message=message,
                channel_id=channel_id,
                requester_slack_id=requester_slack_id,
                thread_ts=thread_ts,
                task_id=str(task_id),
                requester_role=user.role,
                progress_callback=_progress_callback,
            )
            await slack.post_message(
                channel_id,
                text=result_obj.content,
                thread_ts=thread_ts,
            )

        async with session_factory() as db:
            t = await db.get(Task, task_id)
            if t:
                from datetime import datetime
                t.status = TaskStatus.COMPLETED
                t.completed_at = datetime.now(UTC)
                db.add(AuditLog(
                    task_id=task_id,
                    actor_slack_id=requester_slack_id,
                    action="message_processed",
                    success=True,
                ))
                await db.commit()

        return {"task_id": str(task_id), "status": "completed"}

    except NeedsApprovalError as e:
        log.info("task.needs_approval", tool=e.tool_name, task_id=str(task_id))
        approval_wf = ApprovalWorkflow()

        # Embed the LLM tool_call_id so the conversation can resume correctly after approval
        tool_args_with_id = {**e.tool_args, "__tool_call_id__": e.tool_call_id}
        dual = approval_wf.needs_dual_approval(e.tool_name)
        if dual:
            tool_args_with_id["__min_approvers__"] = 2

        async with session_factory() as db:
            approval = await approval_wf.create_approval(
                db=db,
                task_id=task_id,
                tool_name=e.tool_name,
                tool_args=tool_args_with_id,
                description=e.description,
                risk_level=e.risk_level,
                requester_slack_id=requester_slack_id,
                channel_id=channel_id,
            )
            approval_id = approval.id

        blocks = build_approval_blocks(approval)
        notice = "⚠️ *Dual approval required* — this operation needs 2 approvers.\n" if dual else ""
        result = await slack.post_message(
            channel_id,
            text=f"{notice}Approval required: {e.description}",
            blocks=blocks,
            thread_ts=thread_ts,
        )

        async with session_factory() as db:
            from opsbot.models.db import Approval
            a = await db.get(Approval, approval_id)
            if a:
                a.slack_message_ts = result.get("ts")
                await db.commit()

        return {"task_id": str(task_id), "status": "waiting_approval"}

    except Exception as exc:
        log.error("task.failed", task_id=str(task_id), error=str(exc))
        async with session_factory() as db:
            t = await db.get(Task, task_id)
            if t:
                t.status = TaskStatus.FAILED
                t.error = str(exc)
                await db.commit()
        await slack.post_message(
            channel_id,
            text="❌ I ran into an error. Please try again or contact your DevOps team.",
            thread_ts=thread_ts,
        )
        return {"task_id": str(task_id), "status": "failed", "error": str(exc)}


@celery_app.task(name="opsbot.tasks.celery_app.process_approval_task", bind=True)
def process_approval_task(
    self,
    approval_id: str,
    approver_slack_id: str,
    approved: bool,
    reason: str = "",
    channel_id: str | None = None,
    thread_ts: str | None = None,
) -> dict:
    return _run_async(_process_approval(approval_id, approver_slack_id, approved, reason, channel_id, thread_ts))


async def _process_approval(
    approval_id: str,
    approver_slack_id: str,
    approved: bool,
    reason: str,
    channel_id: str | None,
    thread_ts: str | None,
) -> dict:
    from opsbot.agent.engine import AgentEngine
    from opsbot.integrations.slack.client import SlackClient
    from opsbot.models.db import Task
    from opsbot.workflows.approval import ApprovalWorkflow

    slack = SlackClient()
    session_factory = _get_session_factory()
    approval_wf = ApprovalWorkflow()
    aid = uuid.UUID(approval_id)

    async with session_factory() as db:
        if approved:
            approval = await approval_wf.approve(db, aid, approver_slack_id)
        else:
            approval = await approval_wf.deny(db, aid, approver_slack_id, reason)

    if not approved:
        if channel_id:
            await slack.post_message(channel_id, text=f"❌ Operation denied by <@{approver_slack_id}>.", thread_ts=thread_ts)
        return {"status": "denied"}

    # Extract internal metadata stored at approval-creation time
    raw_tool_args = dict(approval.tool_args or {})
    original_tool_call_id = raw_tool_args.pop("__tool_call_id__", "approved")
    min_approvers = raw_tool_args.pop("__min_approvers__", 1)

    # Dual-approval guard: check that a second distinct approver has approved
    if min_approvers >= 2:
        existing_approvers = raw_tool_args.pop("__approvers__", [])
        if approver_slack_id not in existing_approvers:
            existing_approvers.append(approver_slack_id)
        if len(existing_approvers) < min_approvers:
            # Not enough approvers yet — re-open approval and notify
            async with session_factory() as db:
                from opsbot.models.db import Approval, ApprovalStatus
                a = await db.get(Approval, aid)
                if a:
                    a.status = ApprovalStatus.PENDING
                    a.approver_slack_id = None
                    a.resolved_at = None
                    raw_tool_args["__tool_call_id__"] = original_tool_call_id
                    raw_tool_args["__min_approvers__"] = min_approvers
                    raw_tool_args["__approvers__"] = existing_approvers
                    a.tool_args = raw_tool_args
                    await db.commit()
            if channel_id:
                remaining = min_approvers - len(existing_approvers)
                await slack.post_message(
                    channel_id,
                    text=f"✅ <@{approver_slack_id}> approved — {remaining} more approver(s) needed.",
                    thread_ts=thread_ts,
                )
            return {"status": "partial_approval", "approvers": existing_approvers}

    # Execute the approved tool
    try:
        engine = AgentEngine()
        result_obj = await engine.resume_after_approval(
            tool_name=approval.tool_name,
            tool_args=raw_tool_args,
            original_tool_call_id=original_tool_call_id,
            channel_id=channel_id or "",
            thread_ts=thread_ts,
        )
        if channel_id:
            await slack.post_message(channel_id, text=result_obj.content, thread_ts=thread_ts)

        async with session_factory() as db:
            from datetime import datetime

            from opsbot.models.db import AuditLog, TaskStatus
            t = await db.get(Task, approval.task_id)
            if t:
                t.status = TaskStatus.COMPLETED
                t.completed_at = datetime.now(UTC)
                db.add(AuditLog(
                    task_id=approval.task_id,
                    actor_slack_id=approver_slack_id,
                    action=f"executed:{approval.tool_name}",
                    tool_name=approval.tool_name,
                    tool_args=raw_tool_args,
                    risk_level=approval.risk_level,
                    success=True,
                ))
                await db.commit()

        return {"status": "executed", "approval_id": approval_id}

    except Exception as exc:
        log.error("approval.execute.failed", error=str(exc))
        if channel_id:
            await slack.post_message(channel_id, text="❌ Execution failed after approval. Check logs for details.", thread_ts=thread_ts)
        return {"status": "failed", "error": str(exc)}


@celery_app.task(name="opsbot.tasks.celery_app.run_slo_analysis_task")
def run_slo_analysis_task(
    service_name: str,
    namespace: str,
    lookback_days: int,
    requester_slack_id: str,
    channel_id: str,
    thread_ts: str | None = None,
    create_pr: bool = False,
    target_repo: str | None = None,
) -> dict:
    return _run_async(_run_slo_analysis(service_name, namespace, lookback_days, requester_slack_id, channel_id, thread_ts, create_pr, target_repo))


async def _run_slo_analysis(service_name, namespace, lookback_days, requester_slack_id, channel_id, thread_ts, create_pr, target_repo):
    from opsbot.integrations.slack.client import SlackClient
    from opsbot.integrations.slack.formatters import format_slo_proposal
    from opsbot.sre.fix_generator import FixGenerator
    from opsbot.sre.slo_analyzer import SLOAnalyzer

    slack = SlackClient()
    analyzer = SLOAnalyzer()
    result = await analyzer.analyze(service_name=service_name, namespace=namespace, lookback_days=lookback_days)

    report = format_slo_proposal(result)
    await slack.post_message(channel_id, text=report, thread_ts=thread_ts)

    if create_pr and target_repo and result.get("slo_yaml"):
        generator = FixGenerator()
        pr_result = await generator.generate_fix(
            issue_description=f"Add SLO rules for {service_name}",
            root_cause="SLO configuration missing",
            affected_files=[{"path": f"monitoring/slos/{service_name}.yaml", "description": "SLO PrometheusRule"}],
            repo=target_repo,
            auto_create_pr=True,
            requester_slack_id=requester_slack_id,
        )
        if pr_result.get("pr_url"):
            await slack.post_message(channel_id, text=f"📎 PR created: {pr_result['pr_url']}", thread_ts=thread_ts)

    return {"status": "completed", "service": service_name}


@celery_app.task(name="opsbot.tasks.celery_app.expire_approvals_task")
def expire_approvals_task() -> dict:
    return _run_async(_expire_approvals())


async def _expire_approvals():
    from opsbot.workflows.approval import ApprovalWorkflow
    session_factory = _get_session_factory()
    async with session_factory() as db:
        wf = ApprovalWorkflow()
        count = await wf.expire_old_approvals(db)
        if count:
            log.info("approvals.expired", count=count)
    return {"expired": count}


@celery_app.task(name="opsbot.tasks.celery_app.purge_old_audit_logs_task")
def purge_old_audit_logs_task() -> dict:
    return _run_async(_purge_old_audit_logs())


async def _purge_old_audit_logs():
    from datetime import datetime, timedelta

    from sqlalchemy import delete

    from opsbot.models.db import AuditLog
    s = get_settings()
    cutoff = datetime.now(UTC) - timedelta(days=s.audit_log_retention_days)
    session_factory = _get_session_factory()
    async with session_factory() as db:
        result = await db.execute(
            delete(AuditLog).where(AuditLog.created_at < cutoff)
        )
        deleted = result.rowcount
        await db.commit()
    if deleted:
        log.info("audit_logs.purged", count=deleted, older_than_days=s.audit_log_retention_days)
    return {"deleted": deleted}


def cli():
    celery_app.start()
