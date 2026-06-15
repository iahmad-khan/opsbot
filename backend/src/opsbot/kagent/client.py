"""A2A HTTP client for communicating with the KAGENT controller."""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx
import structlog

from opsbot.config.settings import get_settings
from opsbot.kagent.schemas import A2AMessage, A2ARequest, A2ARunEvent, A2ARunParams

log = structlog.get_logger(__name__)


def _kagent_url(path: str) -> str:
    s = get_settings()
    return f"{s.kagent_url.rstrip('/')}{path}"


async def run_agent(
    agent_name: str,
    message: str,
    session_id: str | None = None,
    prior_context: list[dict] | None = None,
) -> AsyncIterator[A2ARunEvent]:
    """
    POST to KAGENT's A2A endpoint and yield parsed SSE events.

    The KAGENT controller streams Server-Sent Events in the form:
        data: {"type": "text", "text": "..."}\n\n
        data: {"type": "approval_required", "approval_crd_name": "...", ...}\n\n
        data: {"type": "final", "text": "..."}\n\n

    Callers should accumulate text events for the full response and handle
    approval_required events by creating their own Slack approval buttons.
    """
    s = get_settings()
    sid = session_id or str(uuid.uuid4())

    payload = A2ARequest(
        params=A2ARunParams(
            message=A2AMessage.user(message),
            session_id=sid,
            metadata={"priorContext": prior_context or []},
        )
    )
    url = _kagent_url(f"/agents/{agent_name}/runs")

    timeout = httpx.Timeout(connect=5.0, read=s.litellm_timeout, write=30.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST",
                url,
                content=payload.model_dump_json(by_alias=True),
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        data = json.loads(raw)
                        yield A2ARunEvent(**data)
                    except (json.JSONDecodeError, Exception) as exc:
                        log.warning("kagent.sse.parse.error", line=raw, error=str(exc))
        except httpx.ConnectError as exc:
            log.error("kagent.connect.error", url=url, error=str(exc))
            yield A2ARunEvent(
                type="error",
                text="❌ Could not reach the KAGENT controller. Is it running?",
                final=True,
            )
        except httpx.HTTPStatusError as exc:
            log.error("kagent.http.error", status=exc.response.status_code, error=str(exc))
            yield A2ARunEvent(
                type="error",
                text=f"❌ KAGENT returned HTTP {exc.response.status_code}.",
                final=True,
            )


async def patch_approval(crd_name: str, approved: bool, reason: str = "") -> bool:
    """PATCH a KAGENT Approval CRD to Approved or Denied."""
    s = get_settings()
    namespace = s.kagent_namespace
    phase = "Approved" if approved else "Denied"
    patch_body = {
        "status": {
            "phase": phase,
            **({"reason": reason} if reason else {}),
        }
    }
    # Use the Kubernetes API via kubernetes-asyncio
    try:
        from kubernetes_asyncio import client as k8s_client  # type: ignore[import]
        from kubernetes_asyncio import config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except Exception:
            await k8s_config.load_kube_config()

        async with k8s_client.ApiClient() as api_client:
            custom_api = k8s_client.CustomObjectsApi(api_client)
            await custom_api.patch_namespaced_custom_object_status(
                group="kagent.dev",
                version="v1alpha1",
                namespace=namespace,
                plural="approvals",
                name=crd_name,
                body=patch_body,
            )
        log.info("kagent.approval.patched", crd=crd_name, phase=phase)
        return True
    except Exception as exc:
        log.error("kagent.approval.patch.failed", crd=crd_name, error=str(exc))
        return False
