from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _client() -> httpx.AsyncClient:
    s = get_settings()
    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if s.bitbucket_token:
        headers["Authorization"] = f"Bearer {s.bitbucket_token}"
    elif s.bitbucket_username and s.bitbucket_app_password:
        creds = base64.b64encode(f"{s.bitbucket_username}:{s.bitbucket_app_password}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    bb_url = s.bitbucket_url.rstrip("/")
    is_cloud = "api.bitbucket.org" in bb_url
    base_url = bb_url if is_cloud else f"{bb_url}/rest/api/1.0"
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0)


def _is_cloud() -> bool:
    return "api.bitbucket.org" in get_settings().bitbucket_url


def _repo_path(workspace: str, repo: str) -> str:
    if _is_cloud():
        return f"/repositories/{workspace}/{repo}"
    return f"/projects/{workspace}/repos/{repo}"


class BitbucketTools:
    def _ws(self, workspace: str | None) -> str:
        return workspace or get_settings().bitbucket_workspace

    async def list_repos(self, workspace: str | None = None, query: str = "") -> dict:
        ws = self._ws(workspace)
        async with _client() as c:
            if _is_cloud():
                params: dict[str, Any] = {"pagelen": 25}
                if query:
                    params["q"] = f'name~"{query}"'
                r = await c.get(f"/repositories/{ws}", params=params)
                r.raise_for_status()
                data = r.json()
                repos = [
                    {"name": x["slug"], "full_name": x["full_name"], "language": x.get("language"), "updated_on": x.get("updated_on")}
                    for x in data.get("values", [])
                ]
            else:
                r = await c.get(f"/projects/{ws}/repos", params={"limit": 25})
                r.raise_for_status()
                data = r.json()
                repos = [{"name": x["slug"], "description": x.get("description")} for x in data.get("values", [])]
        return {"repos": repos, "count": len(repos)}

    async def list_prs(self, repo: str, workspace: str | None = None, state: str = "OPEN") -> dict:
        ws = self._ws(workspace)
        async with _client() as c:
            path = _repo_path(ws, repo)
            endpoint = f"{path}/pullrequests" if _is_cloud() else f"{path}/pull-requests"
            r = await c.get(endpoint, params={"state": state, "pagelen" if _is_cloud() else "limit": 25})
            r.raise_for_status()
            data = r.json()
        prs = [
            {
                "id": x["id"],
                "title": x["title"],
                "state": x["state"],
                "author": x.get("author", {}).get("display_name") or x.get("author", {}).get("displayName"),
                "source": x.get("source", {}).get("branch", {}).get("name") or x.get("fromRef", {}).get("displayId"),
                "destination": x.get("destination", {}).get("branch", {}).get("name") or x.get("toRef", {}).get("displayId"),
            }
            for x in data.get("values", [])
        ]
        return {"prs": prs, "count": len(prs)}

    async def create_pr(
        self,
        repo: str,
        title: str,
        source_branch: str,
        destination_branch: str = "main",
        description: str = "",
        workspace: str | None = None,
        reviewers: list[str] | None = None,
    ) -> dict:
        ws = self._ws(workspace)
        async with _client() as c:
            path = _repo_path(ws, repo)
            if _is_cloud():
                body: dict[str, Any] = {
                    "title": title,
                    "description": description,
                    "source": {"branch": {"name": source_branch}},
                    "destination": {"branch": {"name": destination_branch}},
                    "reviewers": [{"uuid": u} for u in (reviewers or [])],
                }
                r = await c.post(f"{path}/pullrequests", json=body)
            else:
                body = {
                    "title": title,
                    "description": description,
                    "fromRef": {"id": f"refs/heads/{source_branch}"},
                    "toRef": {"id": f"refs/heads/{destination_branch}"},
                    "reviewers": [{"user": {"name": u}} for u in (reviewers or [])],
                }
                r = await c.post(f"{path}/pull-requests", json=body)
            r.raise_for_status()
            data = r.json()
        log.info("bitbucket.create_pr", repo=repo, title=title)
        return {"id": data["id"], "title": data["title"], "status": "created"}

    async def merge_pr(
        self,
        repo: str,
        pr_id: int,
        workspace: str | None = None,
        merge_strategy: str = "merge_commit",
    ) -> dict:
        ws = self._ws(workspace)
        async with _client() as c:
            path = _repo_path(ws, repo)
            if _is_cloud():
                r = await c.post(f"{path}/pullrequests/{pr_id}/merge", json={"merge_strategy": merge_strategy})
            else:
                # Get version for optimistic lock
                rv = await c.get(f"{path}/pull-requests/{pr_id}")
                rv.raise_for_status()
                r = await c.post(f"{path}/pull-requests/{pr_id}/merge", json={"version": rv.json()["version"]})
            r.raise_for_status()
        log.info("bitbucket.merge_pr", repo=repo, pr_id=pr_id)
        return {"repo": repo, "pr_id": pr_id, "status": "merged"}

    async def get_pipeline_status(self, repo: str, branch: str = "main", workspace: str | None = None) -> dict:
        ws = self._ws(workspace)
        async with _client() as c:
            r = await c.get(
                f"{_repo_path(ws, repo)}/pipelines/",
                params={"target.branch": branch, "sort": "-created_on", "pagelen": 5},
            )
            r.raise_for_status()
            data = r.json()
        pipelines = [
            {
                "uuid": x.get("uuid"),
                "state": x.get("state", {}).get("name"),
                "result": x.get("state", {}).get("result", {}).get("name"),
                "created": x.get("created_on"),
                "duration_seconds": x.get("duration_in_seconds"),
            }
            for x in data.get("values", [])
        ]
        return {"branch": branch, "pipelines": pipelines}

    async def trigger_pipeline(
        self,
        repo: str,
        branch: str,
        workspace: str | None = None,
        variables: list[dict] | None = None,
    ) -> dict:
        ws = self._ws(workspace)
        body: dict[str, Any] = {
            "target": {"type": "pipeline_ref_target", "ref_type": "branch", "ref_name": branch}
        }
        if variables:
            body["variables"] = variables
        async with _client() as c:
            r = await c.post(f"{_repo_path(ws, repo)}/pipelines/", json=body)
            r.raise_for_status()
            data = r.json()
        log.info("bitbucket.trigger_pipeline", repo=repo, branch=branch)
        return {"uuid": data.get("uuid"), "state": data.get("state", {}).get("name"), "branch": branch}

    async def create_branch(self, repo: str, branch_name: str, source: str = "main", workspace: str | None = None) -> dict:
        ws = self._ws(workspace)
        async with _client() as c:
            path = _repo_path(ws, repo)
            if _is_cloud():
                r = await c.post(f"{path}/refs/branches", json={"name": branch_name, "target": {"hash": source}})
            else:
                r = await c.post(f"{path}/branches", json={"name": branch_name, "startPoint": source})
            r.raise_for_status()
        return {"branch": branch_name, "source": source, "repo": repo, "status": "created"}
