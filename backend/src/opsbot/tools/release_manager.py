"""
Release Manager — cross-cutting release awareness tool.

Answers questions like:
  - What tag/version is running in production for service X?
  - What is the rollback target for service X?
  - What tags are available that haven't been deployed yet?
  - What changed between the current and previous tag?
  - Show the release history for service X across all environments.
  - Which services are on outdated images?
  - Compare what's in staging vs production.

Data is gathered from:
  - Kubernetes (live running image tags via deployment specs)
  - ArgoCD (deployment history, sync revisions)
  - GitHub / GitLab / Bitbucket (available tags, commit diffs)
  - AuditLog DB (past deployments recorded by the bot itself)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_image_tag(image: str) -> tuple[str, str]:
    """Split 'registry/repo/name:tag' into (name, tag). Returns (image, 'latest') if no tag."""
    if ":" in image:
        name, tag = image.rsplit(":", 1)
        return name, tag
    return image, "latest"


def _argocd_headers() -> dict[str, str]:
    s = get_settings()
    return {"Authorization": f"Bearer {s.argocd_token}", "Content-Type": "application/json"}


def _argocd_base() -> str:
    s = get_settings()
    return s.argocd_server_url.rstrip("/") + "/api/v1"


def _github_headers() -> dict[str, str]:
    s = get_settings()
    return {"Authorization": f"Bearer {s.github_token}", "Accept": "application/vnd.github+json"}


def _gitlab_headers() -> dict[str, str]:
    s = get_settings()
    return {"PRIVATE-TOKEN": s.gitlab_token}


def _gitlab_base() -> str:
    s = get_settings()
    return s.gitlab_url.rstrip("/") + "/api/v4"


# ---------------------------------------------------------------------------
# Core Tool Methods
# ---------------------------------------------------------------------------

class ReleaseManager:

    # ------------------------------------------------------------------
    # 1. What tag is running right now?
    # ------------------------------------------------------------------

    async def get_release_status(
        self,
        service: str,
        environment: str | None = None,
        namespace: str | None = None,
    ) -> dict:
        """
        Return the currently deployed image/tag for a service, across all known
        environments or just the requested one.

        Sources: Kubernetes deployments + ArgoCD app status.
        """
        results: list[dict] = []

        # Kubernetes — scan all namespaces (or the specified one)
        try:
            from kubernetes_asyncio import client as k8s_client, config as k8s_config
            try:
                k8s_config.load_incluster_config()
            except Exception:
                await k8s_config.load_kube_config()

            apps_v1 = k8s_client.AppsV1Api()
            if namespace:
                ns_list = [namespace]
            else:
                core_v1 = k8s_client.CoreV1Api()
                ns_resp = await core_v1.list_namespace()
                ns_list = [ns.metadata.name for ns in ns_resp.items]

            for ns in ns_list:
                try:
                    deps = await apps_v1.list_namespaced_deployment(namespace=ns)
                    for dep in deps.items:
                        name = dep.metadata.name
                        if service.lower() not in name.lower():
                            continue
                        for container in dep.spec.template.spec.containers:
                            _, tag = _parse_image_tag(container.image)
                            results.append({
                                "source": "kubernetes",
                                "service": name,
                                "namespace": ns,
                                "image": container.image,
                                "tag": tag,
                                "ready_replicas": dep.status.ready_replicas or 0,
                                "desired_replicas": dep.spec.replicas or 1,
                            })
                except Exception:
                    pass
        except Exception as exc:
            log.warning("release_manager.k8s.failed", error=str(exc))

        # ArgoCD — check if there's an app matching the service name
        s = get_settings()
        if s.argocd_server_url and s.argocd_token:
            try:
                async with httpx.AsyncClient(verify=not s.argocd_insecure, timeout=15) as c:
                    r = await c.get(f"{_argocd_base()}/applications", headers=_argocd_headers())
                    r.raise_for_status()
                    for app in r.json().get("items", []):
                        app_name = app["metadata"]["name"]
                        if service.lower() not in app_name.lower():
                            continue
                        sync = app["status"]["sync"]
                        health = app["status"]["health"]
                        images = app["status"].get("summary", {}).get("images", [])
                        image_tags = [_parse_image_tag(img)[1] for img in images]
                        results.append({
                            "source": "argocd",
                            "app": app_name,
                            "sync_status": sync["status"],
                            "health_status": health["status"],
                            "revision": sync.get("revision", "")[:12],
                            "images": images,
                            "image_tags": image_tags,
                            "destination_namespace": app["spec"]["destination"].get("namespace"),
                        })
            except Exception as exc:
                log.warning("release_manager.argocd.failed", error=str(exc))

        # AuditLog — last known deployment by the bot
        try:
            from opsbot.models.db import AuditLog, make_session_factory
            from sqlalchemy import select, desc
            factory = make_session_factory()
            async with factory() as db:
                q = (
                    select(AuditLog)
                    .where(AuditLog.service_name == service)
                    .where(AuditLog.success == True)  # noqa: E712
                    .where(AuditLog.image_tag.isnot(None))
                    .order_by(desc(AuditLog.created_at))
                    .limit(5)
                )
                if environment:
                    q = q.where(AuditLog.environment == environment)
                rows = (await db.execute(q)).scalars().all()
                if rows:
                    results.append({
                        "source": "opsbot_audit",
                        "last_deployments": [
                            {
                                "environment": r.environment,
                                "image_tag": r.image_tag,
                                "deployed_by": r.actor_slack_id,
                                "deployed_at": r.created_at.isoformat() if r.created_at else None,
                            }
                            for r in rows
                        ],
                    })
        except Exception as exc:
            log.warning("release_manager.audit.failed", error=str(exc))

        if not results:
            return {"service": service, "error": f"No deployment found for '{service}'"}

        return {"service": service, "environment": environment, "deployments": results}

    # ------------------------------------------------------------------
    # 2. What should we roll back to?
    # ------------------------------------------------------------------

    async def get_rollback_target(self, service: str, environment: str | None = None) -> dict:
        """
        Return the previous stable tag for a service — the recommended rollback target.

        Logic: look at ArgoCD history (previous synced revision) and AuditLog
        (last successful deploy before the current one).
        """
        rollback_options: list[dict] = []

        # ArgoCD history
        s = get_settings()
        if s.argocd_server_url and s.argocd_token:
            try:
                async with httpx.AsyncClient(verify=not s.argocd_insecure, timeout=15) as c:
                    # Find the matching app
                    r = await c.get(f"{_argocd_base()}/applications", headers=_argocd_headers())
                    r.raise_for_status()
                    for app in r.json().get("items", []):
                        if service.lower() not in app["metadata"]["name"].lower():
                            continue
                        app_name = app["metadata"]["name"]
                        current_revision = app["status"]["sync"].get("revision", "")

                        hist_r = await c.get(
                            f"{_argocd_base()}/applications/{app_name}/revisions",
                            headers=_argocd_headers(),
                        )
                        hist_r.raise_for_status()
                        history = hist_r.json().get("items", [])
                        # Skip the current revision, take the one before
                        previous = [
                            h for h in history
                            if h.get("revision", "") != current_revision
                        ]
                        if previous:
                            prev = previous[0]
                            rollback_options.append({
                                "source": "argocd",
                                "app": app_name,
                                "current_revision": current_revision[:12],
                                "rollback_revision": prev.get("revision", "")[:12],
                                "rollback_revision_id": prev.get("id"),
                                "deployed_at": prev.get("deployedAt"),
                                "initiator": prev.get("initiatedBy", {}).get("username"),
                            })
            except Exception as exc:
                log.warning("release_manager.rollback.argocd.failed", error=str(exc))

        # AuditLog — last two successful deploys, second one is the rollback target
        try:
            from opsbot.models.db import AuditLog, make_session_factory
            from sqlalchemy import select, desc
            factory = make_session_factory()
            async with factory() as db:
                q = (
                    select(AuditLog)
                    .where(AuditLog.service_name == service)
                    .where(AuditLog.success == True)  # noqa: E712
                    .where(AuditLog.image_tag.isnot(None))
                    .order_by(desc(AuditLog.created_at))
                    .limit(2)
                )
                if environment:
                    q = q.where(AuditLog.environment == environment)
                rows = (await db.execute(q)).scalars().all()
                if len(rows) >= 2:
                    current, previous = rows[0], rows[1]
                    rollback_options.append({
                        "source": "opsbot_audit",
                        "current_tag": current.image_tag,
                        "current_deployed_at": current.created_at.isoformat() if current.created_at else None,
                        "rollback_tag": previous.image_tag,
                        "rollback_deployed_at": previous.created_at.isoformat() if previous.created_at else None,
                        "rollback_deployed_by": previous.actor_slack_id,
                    })
        except Exception as exc:
            log.warning("release_manager.rollback.audit.failed", error=str(exc))

        if not rollback_options:
            return {"service": service, "error": "No rollback history found. This may be the first deployment."}

        return {"service": service, "environment": environment, "rollback_options": rollback_options}

    # ------------------------------------------------------------------
    # 3. What tags are available in the registry?
    # ------------------------------------------------------------------

    async def get_available_releases(
        self,
        service: str,
        repo: str | None = None,
        limit: int = 20,
    ) -> dict:
        """
        List available release tags for a service from GitHub/GitLab/Bitbucket.
        Marks which tag is currently deployed.
        """
        tags: list[dict] = []
        s = get_settings()

        # GitHub
        if s.github_token and (repo or s.github_org):
            target_repo = repo or f"{s.github_org}/{service}"
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.get(
                        f"https://api.github.com/repos/{target_repo}/tags",
                        headers=_github_headers(),
                        params={"per_page": limit},
                    )
                    r.raise_for_status()
                    for t in r.json():
                        tags.append({
                            "source": "github",
                            "tag": t["name"],
                            "commit": t["commit"]["sha"][:12],
                            "repo": target_repo,
                        })
            except Exception as exc:
                log.warning("release_manager.tags.github.failed", error=str(exc))

        # GitLab
        if not tags and s.gitlab_token:
            project = repo or f"{s.gitlab_default_group}/{service}"
            encoded = project.replace("/", "%2F")
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.get(
                        f"{_gitlab_base()}/projects/{encoded}/repository/tags",
                        headers=_gitlab_headers(),
                        params={"per_page": limit, "order_by": "updated", "sort": "desc"},
                    )
                    r.raise_for_status()
                    for t in r.json():
                        tags.append({
                            "source": "gitlab",
                            "tag": t["name"],
                            "commit": (t.get("commit") or {}).get("id", "")[:12],
                            "created_at": t.get("created_at"),
                            "release": t.get("release"),
                            "repo": project,
                        })
            except Exception as exc:
                log.warning("release_manager.tags.gitlab.failed", error=str(exc))

        # Cross-reference with currently deployed tag
        try:
            status = await self.get_release_status(service)
            deployed_tags: set[str] = set()
            for dep in status.get("deployments", []):
                if dep.get("tag"):
                    deployed_tags.add(dep["tag"])
                for img_tag in dep.get("image_tags", []):
                    deployed_tags.add(img_tag)
            for t in tags:
                t["currently_deployed"] = t["tag"] in deployed_tags
        except Exception:
            pass

        return {
            "service": service,
            "available_tags": tags[:limit],
            "total_found": len(tags),
        }

    # ------------------------------------------------------------------
    # 4. What changed between two tags?
    # ------------------------------------------------------------------

    async def get_release_diff(
        self,
        service: str,
        from_tag: str,
        to_tag: str,
        repo: str | None = None,
    ) -> dict:
        """
        Show commits, PRs/MRs, and files changed between two tags.
        Tries GitHub first, then GitLab.
        """
        s = get_settings()

        # GitHub compare
        if s.github_token:
            target_repo = repo or (f"{s.github_org}/{service}" if s.github_org else None)
            if target_repo:
                try:
                    async with httpx.AsyncClient(timeout=15) as c:
                        r = await c.get(
                            f"https://api.github.com/repos/{target_repo}/compare/{from_tag}...{to_tag}",
                            headers=_github_headers(),
                        )
                        r.raise_for_status()
                        data = r.json()
                        commits = [
                            {
                                "sha": c_["sha"][:12],
                                "message": c_["commit"]["message"].split("\n")[0][:120],
                                "author": c_["commit"]["author"]["name"],
                                "date": c_["commit"]["author"]["date"],
                            }
                            for c_ in data.get("commits", [])[:30]
                        ]
                        files_changed = [
                            {"file": f["filename"], "changes": f["changes"], "status": f["status"]}
                            for f in data.get("files", [])[:20]
                        ]
                        return {
                            "service": service,
                            "from_tag": from_tag,
                            "to_tag": to_tag,
                            "source": "github",
                            "repo": target_repo,
                            "total_commits": data.get("total_commits", len(commits)),
                            "status": data.get("status"),
                            "commits": commits,
                            "files_changed": files_changed,
                            "diff_url": data.get("html_url"),
                        }
                except Exception as exc:
                    log.warning("release_manager.diff.github.failed", error=str(exc))

        # GitLab compare
        if s.gitlab_token:
            project = repo or (f"{s.gitlab_default_group}/{service}" if s.gitlab_default_group else service)
            encoded = project.replace("/", "%2F")
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.get(
                        f"{_gitlab_base()}/projects/{encoded}/repository/compare",
                        headers=_gitlab_headers(),
                        params={"from": from_tag, "to": to_tag},
                    )
                    r.raise_for_status()
                    data = r.json()
                    commits = [
                        {
                            "sha": c_["id"][:12],
                            "message": c_["title"][:120],
                            "author": c_["author_name"],
                            "date": c_["authored_date"],
                        }
                        for c_ in data.get("commits", [])[:30]
                    ]
                    diffs = [
                        {"file": d["new_path"], "status": "modified" if not d["new_file"] else "added"}
                        for d in data.get("diffs", [])[:20]
                    ]
                    return {
                        "service": service,
                        "from_tag": from_tag,
                        "to_tag": to_tag,
                        "source": "gitlab",
                        "repo": project,
                        "total_commits": len(commits),
                        "commits": commits,
                        "files_changed": diffs,
                    }
            except Exception as exc:
                log.warning("release_manager.diff.gitlab.failed", error=str(exc))

        return {"service": service, "error": "Could not retrieve diff — check GitHub/GitLab token config"}

    # ------------------------------------------------------------------
    # 5. Full deployment history for a service
    # ------------------------------------------------------------------

    async def get_release_history(
        self,
        service: str,
        environment: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Return the last N deployments for a service from the AuditLog."""
        try:
            from opsbot.models.db import AuditLog, make_session_factory
            from sqlalchemy import select, desc, or_
            factory = make_session_factory()
            async with factory() as db:
                q = (
                    select(AuditLog)
                    .where(
                        or_(
                            AuditLog.service_name == service,
                            AuditLog.tool_args.op("->>")(  # type: ignore[attr-defined]
                                "service"
                            ).contains(service),
                        )
                    )
                    .where(AuditLog.success == True)  # noqa: E712
                    .order_by(desc(AuditLog.created_at))
                    .limit(limit)
                )
                if environment:
                    q = q.where(AuditLog.environment == environment)
                rows = (await db.execute(q)).scalars().all()

            history = [
                {
                    "environment": r.environment,
                    "image_tag": r.image_tag,
                    "tool": r.tool_name,
                    "deployed_by": r.actor_slack_id,
                    "deployed_at": r.created_at.isoformat() if r.created_at else None,
                    "action": r.action,
                }
                for r in rows
            ]
            return {"service": service, "environment": environment, "history": history, "count": len(history)}
        except Exception as exc:
            log.error("release_manager.history.failed", error=str(exc))
            return {"service": service, "error": str(exc)}

    # ------------------------------------------------------------------
    # 6. Compare two environments
    # ------------------------------------------------------------------

    async def compare_environments(
        self,
        service: str,
        env_a: str,
        env_b: str,
    ) -> dict:
        """
        Compare what's deployed in env_a vs env_b for a service.
        E.g.: 'staging is on v1.2.5, production is on v1.2.3 — 2 versions behind'
        """
        status_a = await self.get_release_status(service, environment=env_a)
        status_b = await self.get_release_status(service, environment=env_b)

        def _extract_tags(status: dict) -> set[str]:
            tags: set[str] = set()
            for dep in status.get("deployments", []):
                if dep.get("tag"):
                    tags.add(dep["tag"])
                for img_tag in dep.get("image_tags", []):
                    tags.add(img_tag)
            return tags

        tags_a = _extract_tags(status_a)
        tags_b = _extract_tags(status_b)

        in_sync = tags_a == tags_b
        return {
            "service": service,
            env_a: sorted(tags_a),
            env_b: sorted(tags_b),
            "in_sync": in_sync,
            "summary": (
                f"{env_a} and {env_b} are running the same version: {', '.join(tags_a)}"
                if in_sync
                else f"{env_a} is on {', '.join(tags_a) or 'unknown'}, "
                     f"{env_b} is on {', '.join(tags_b) or 'unknown'}"
            ),
        }

    # ------------------------------------------------------------------
    # 7. Find stale services
    # ------------------------------------------------------------------

    async def get_stale_services(
        self,
        environment: str | None = None,
        threshold_days: int = 30,
    ) -> dict:
        """
        List services that haven't been updated in more than threshold_days.
        Uses AuditLog deployment records.
        """
        try:
            from opsbot.models.db import AuditLog, make_session_factory
            from sqlalchemy import select, func, desc
            factory = make_session_factory()
            cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)

            async with factory() as db:
                q = (
                    select(
                        AuditLog.service_name,
                        AuditLog.environment,
                        AuditLog.image_tag,
                        func.max(AuditLog.created_at).label("last_deployed_at"),
                    )
                    .where(AuditLog.service_name.isnot(None))
                    .where(AuditLog.success == True)  # noqa: E712
                    .group_by(AuditLog.service_name, AuditLog.environment, AuditLog.image_tag)
                    .order_by(desc("last_deployed_at"))
                )
                if environment:
                    q = q.where(AuditLog.environment == environment)
                rows = (await db.execute(q)).all()

            stale = [
                {
                    "service": r.service_name,
                    "environment": r.environment,
                    "current_tag": r.image_tag,
                    "last_deployed_at": r.last_deployed_at.isoformat() if r.last_deployed_at else None,
                    "days_since_deploy": (datetime.now(timezone.utc) - r.last_deployed_at).days
                    if r.last_deployed_at
                    else None,
                }
                for r in rows
                if r.last_deployed_at and r.last_deployed_at < cutoff
            ]
            return {
                "threshold_days": threshold_days,
                "environment": environment,
                "stale_services": stale,
                "count": len(stale),
            }
        except Exception as exc:
            log.error("release_manager.stale.failed", error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 8. Promote a release between environments
    # ------------------------------------------------------------------

    async def get_promotion_plan(
        self,
        service: str,
        from_env: str,
        to_env: str,
    ) -> dict:
        """
        Build a promotion plan: show what tag is in from_env, confirm it's not
        already in to_env, and return the exact deploy command to execute.
        This is READ-only — it doesn't execute anything; execution goes through
        the normal DESTRUCTIVE approval flow.
        """
        status = await self.get_release_status(service, environment=from_env)
        deployments = status.get("deployments", [])

        tags_in_source: list[str] = []
        for dep in deployments:
            if dep.get("tag"):
                tags_in_source.append(dep["tag"])
            tags_in_source.extend(dep.get("image_tags", []))

        tags_in_source = list(dict.fromkeys(tags_in_source))  # dedupe, preserve order

        if not tags_in_source:
            return {
                "service": service,
                "error": f"Could not determine the current tag in {from_env}. "
                         "Check that Kubernetes or ArgoCD is configured.",
            }

        target_tag = tags_in_source[0]
        diff_summary = None
        try:
            target_status = await self.get_release_status(service, environment=to_env)
            target_tags = []
            for dep in target_status.get("deployments", []):
                if dep.get("tag"):
                    target_tags.append(dep["tag"])
                target_tags.extend(dep.get("image_tags", []))
            if target_tags and target_tags[0] != target_tag:
                diff_summary = f"{to_env} is on {target_tags[0]}, {from_env} is on {target_tag}"
        except Exception:
            pass

        return {
            "service": service,
            "source_environment": from_env,
            "target_environment": to_env,
            "tag_to_promote": target_tag,
            "diff_summary": diff_summary,
            "note": (
                f"To promote, ask: 'deploy {service} tag {target_tag} to {to_env}'. "
                "This will go through the normal approval flow."
            ),
        }
