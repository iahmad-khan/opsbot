"""
KAGENT Approval CRD watcher.

Runs as a background asyncio task inside the FastAPI process.
Watches for KAGENT Approval CRDs in Pending phase and posts Slack buttons.
When KAGENT resumes after approval, the execution result is streamed back
through the A2A response that the Slack relay is holding.
"""
from __future__ import annotations

import asyncio
import json

import structlog

log = structlog.get_logger(__name__)

_NOTIFIED: set[str] = set()  # CRD names already posted to Slack


async def watch_approvals() -> None:
    """
    Main loop: watch KAGENT Approval CRDs, post Slack buttons for new ones.
    Runs forever; cancelled by FastAPI lifespan on shutdown.
    """
    try:
        from kubernetes_asyncio import client as k8s_client  # type: ignore[import]
        from kubernetes_asyncio import config as k8s_config
        from kubernetes_asyncio import watch as k8s_watch
    except ImportError:
        log.warning("kagent.watcher.skip", reason="kubernetes_asyncio not installed or not in-cluster")
        return

    from opsbot.config.settings import get_settings
    s = get_settings()

    # Load kubeconfig (in-cluster first, fall back to ~/.kube/config)
    try:
        k8s_config.load_incluster_config()
    except Exception:
        try:
            await k8s_config.load_kube_config()
        except Exception as exc:
            log.warning("kagent.watcher.no_kubeconfig", error=str(exc))
            return

    custom_api = k8s_client.CustomObjectsApi()
    watcher = k8s_watch.Watch()

    log.info("kagent.approval.watcher.started", namespace=s.kagent_namespace)

    while True:
        try:
            async for event in watcher.stream(
                custom_api.list_namespaced_custom_object,
                group="kagent.dev",
                version="v1alpha1",
                namespace=s.kagent_namespace,
                plural="approvals",
                timeout_seconds=60,
            ):
                obj = event.get("object", {})
                crd_name = obj.get("metadata", {}).get("name", "")
                phase = obj.get("status", {}).get("phase", "")

                if phase == "Pending" and crd_name and crd_name not in _NOTIFIED:
                    _NOTIFIED.add(crd_name)
                    asyncio.create_task(_post_slack_button(obj))

        except asyncio.CancelledError:
            log.info("kagent.approval.watcher.stopped")
            raise
        except Exception as exc:
            log.error("kagent.approval.watcher.error", error=str(exc))
            await asyncio.sleep(10)
            continue
        # Normal stream timeout — pause briefly before restarting to avoid hammering the API
        await asyncio.sleep(1)


async def _post_slack_button(approval_obj: dict) -> None:
    """Build and post a Slack approval button for a pending KAGENT Approval CRD."""
    try:
        from opsbot.integrations.slack.client import SlackClient
        from opsbot.models.db import Approval, make_session_factory
        from opsbot.workflows.approval import ApprovalWorkflow
        from opsbot.workflows.notification import build_approval_blocks

        annotations = approval_obj.get("metadata", {}).get("annotations", {})
        spec = approval_obj.get("spec", {})
        crd_name = approval_obj.get("metadata", {}).get("name", "")

        channel_id = annotations.get("opsbot.dev/channel-id", "")
        thread_ts = annotations.get("opsbot.dev/thread-ts") or None
        requester_slack_id = annotations.get("opsbot.dev/requester-slack-id", "")
        task_id_str = annotations.get("opsbot.dev/task-id") or None
        tool_name = spec.get("toolCall", {}).get("name", "unknown")
        tool_args = spec.get("toolCall", {}).get("arguments", {})
        if isinstance(tool_args, str):
            tool_args = json.loads(tool_args)
        description = annotations.get("opsbot.dev/description") or f"Execute `{tool_name}`"
        risk_level = annotations.get("opsbot.dev/risk-level", "DESTRUCTIVE")

        if not channel_id or not requester_slack_id:
            log.warning("kagent.watcher.missing_annotations", crd=crd_name)
            return

        # Embed the CRD name into tool_args so the approval route can patch it
        full_tool_args = {**tool_args, "__kagent_approval_crd__": crd_name}

        import uuid
        session_factory = make_session_factory()
        approval_wf = ApprovalWorkflow()

        async with session_factory() as db:
            task_id = uuid.UUID(task_id_str) if task_id_str else None
            approval = await approval_wf.create_approval(
                db=db,
                task_id=task_id,
                tool_name=tool_name,
                tool_args=full_tool_args,
                description=description,
                risk_level=risk_level,
                requester_slack_id=requester_slack_id,
                channel_id=channel_id,
            )
            approval_id = approval.id

        blocks = build_approval_blocks(approval)
        slack = SlackClient()
        result = await slack.post_message(
            channel_id,
            text=f"Approval required: {description}",
            blocks=blocks,
            thread_ts=thread_ts,
        )

        async with session_factory() as db:
            a = await db.get(Approval, approval_id)
            if a:
                a.slack_message_ts = result.get("ts")
                await db.commit()

        log.info("kagent.watcher.approval_posted", crd=crd_name, channel=channel_id)

    except Exception as exc:
        log.error("kagent.watcher.post_failed", error=str(exc))
        # Remove from notified set so a future watch cycle can retry
        crd_name_on_error = approval_obj.get("metadata", {}).get("name", "")
        _NOTIFIED.discard(crd_name_on_error)
