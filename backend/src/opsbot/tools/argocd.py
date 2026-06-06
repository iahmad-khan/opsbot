from __future__ import annotations

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _headers() -> dict[str, str]:
    s = get_settings()
    return {"Authorization": f"Bearer {s.argocd_token}", "Content-Type": "application/json"}


def _base_url() -> str:
    s = get_settings()
    return s.argocd_server_url.rstrip("/") + "/api/v1"


class ArgoCDTools:
    async def list_apps(self, namespace: str | None = None) -> dict:
        async with httpx.AsyncClient(verify=not get_settings().argocd_insecure) as c:
            params = {}
            if namespace:
                params["appNamespace"] = namespace
            r = await c.get(f"{_base_url()}/applications", headers=_headers(), params=params)
            r.raise_for_status()
            apps = r.json().get("items", [])
            return {
                "apps": [
                    {
                        "name": a["metadata"]["name"],
                        "namespace": a["metadata"].get("namespace"),
                        "sync_status": a["status"]["sync"]["status"],
                        "health_status": a["status"]["health"]["status"],
                        "destination_server": a["spec"]["destination"].get("server"),
                        "destination_namespace": a["spec"]["destination"].get("namespace"),
                        "source": a["spec"].get("source", {}).get("repoURL"),
                        "revision": a["status"]["sync"].get("revision", "")[:8],
                    }
                    for a in apps
                ],
                "count": len(apps),
            }

    async def get_app(self, app_name: str) -> dict:
        async with httpx.AsyncClient(verify=not get_settings().argocd_insecure) as c:
            r = await c.get(f"{_base_url()}/applications/{app_name}", headers=_headers())
            r.raise_for_status()
            a = r.json()
            return {
                "name": a["metadata"]["name"],
                "sync_status": a["status"]["sync"]["status"],
                "health_status": a["status"]["health"]["status"],
                "revision": a["status"]["sync"].get("revision", ""),
                "images": a["status"].get("summary", {}).get("images", []),
                "conditions": a["status"].get("conditions", []),
            }

    async def sync_app(self, app_name: str, revision: str | None = None, prune: bool = False, dry_run: bool = False) -> dict:
        payload: dict = {}
        if revision:
            payload["revision"] = revision
        if prune:
            payload["prune"] = True
        if dry_run:
            payload["dryRun"] = True
        async with httpx.AsyncClient(verify=not get_settings().argocd_insecure) as c:
            r = await c.post(f"{_base_url()}/applications/{app_name}/sync", headers=_headers(), json=payload)
            r.raise_for_status()
            log.info("argocd.sync", app=app_name)
            return {"app": app_name, "status": "sync_triggered", "dry_run": dry_run}

    async def rollback_app(self, app_name: str, revision_id: int) -> dict:
        payload = {"id": revision_id}
        async with httpx.AsyncClient(verify=not get_settings().argocd_insecure) as c:
            r = await c.post(f"{_base_url()}/applications/{app_name}/rollback", headers=_headers(), json=payload)
            r.raise_for_status()
            log.info("argocd.rollback", app=app_name, revision=revision_id)
            return {"app": app_name, "revision": revision_id, "status": "rollback_triggered"}

    async def get_app_history(self, app_name: str) -> dict:
        async with httpx.AsyncClient(verify=not get_settings().argocd_insecure) as c:
            r = await c.get(f"{_base_url()}/applications/{app_name}/revisions", headers=_headers())
            r.raise_for_status()
            revisions = r.json().get("items", [])
            return {
                "app": app_name,
                "history": [
                    {
                        "id": rev.get("id"),
                        "revision": rev.get("revision", "")[:8],
                        "deployed_at": rev.get("deployedAt"),
                        "initiator": rev.get("initiatedBy", {}).get("username"),
                    }
                    for rev in revisions[:10]
                ],
            }

    async def refresh_app(self, app_name: str, hard: bool = False) -> dict:
        params = {"refresh": "hard" if hard else "normal"}
        async with httpx.AsyncClient(verify=not get_settings().argocd_insecure) as c:
            r = await c.get(f"{_base_url()}/applications/{app_name}", headers=_headers(), params=params)
            r.raise_for_status()
            return {"app": app_name, "status": "refreshed", "hard": hard}
