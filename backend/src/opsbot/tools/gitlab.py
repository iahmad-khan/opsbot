from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _client() -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        base_url=f"{s.gitlab_url.rstrip('/')}/api/v4",
        headers={"PRIVATE-TOKEN": s.gitlab_token, "Content-Type": "application/json"},
        timeout=30.0,
    )


def _encode(project: str) -> str:
    return quote(project, safe="")


class GitLabTools:
    async def list_projects(self, group: str = "", search: str = "") -> dict:
        s = get_settings()
        async with _client() as c:
            if group or s.gitlab_default_group:
                params: dict[str, Any] = {"per_page": 25, "include_subgroups": True}
                if search:
                    params["search"] = search
                r = await c.get(f"/groups/{_encode(group or s.gitlab_default_group)}/projects", params=params)
            else:
                params = {"per_page": 25, "membership": True}
                if search:
                    params["search"] = search
                r = await c.get("/projects", params=params)
            r.raise_for_status()
            data = r.json()
        return {
            "projects": [
                {"id": p["id"], "name": p["name"], "path": p["path_with_namespace"], "web_url": p["web_url"]}
                for p in data
            ],
            "count": len(data),
        }

    async def list_mrs(self, project: str, state: str = "opened", assignee: str = "") -> dict:
        params: dict[str, Any] = {"state": state, "per_page": 25}
        if assignee:
            params["assignee_username"] = assignee
        async with _client() as c:
            r = await c.get(f"/projects/{_encode(project)}/merge_requests", params=params)
            r.raise_for_status()
            data = r.json()
        mrs = [
            {
                "iid": mr["iid"],
                "title": mr["title"],
                "state": mr["state"],
                "author": mr["author"]["username"],
                "source_branch": mr["source_branch"],
                "target_branch": mr["target_branch"],
                "pipeline_status": mr.get("pipeline", {}).get("status"),
                "web_url": mr["web_url"],
            }
            for mr in data
        ]
        return {"mrs": mrs, "count": len(mrs)}

    async def create_mr(
        self,
        project: str,
        title: str,
        source_branch: str,
        target_branch: str = "main",
        description: str = "",
    ) -> dict:
        body = {
            "title": title,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "description": description,
            "remove_source_branch": False,
        }
        async with _client() as c:
            r = await c.post(f"/projects/{_encode(project)}/merge_requests", json=body)
            r.raise_for_status()
            data = r.json()
        log.info("gitlab.create_mr", project=project, title=title)
        return {"iid": data["iid"], "title": data["title"], "web_url": data["web_url"], "status": "created"}

    async def merge_mr(self, project: str, mr_iid: int, squash: bool = False) -> dict:
        async with _client() as c:
            r = await c.put(
                f"/projects/{_encode(project)}/merge_requests/{mr_iid}/merge",
                json={"squash": squash},
            )
            r.raise_for_status()
        log.info("gitlab.merge_mr", project=project, mr_iid=mr_iid)
        return {"project": project, "mr_iid": mr_iid, "status": "merged"}

    async def list_issues(self, project: str, state: str = "opened", search: str = "") -> dict:
        params: dict[str, Any] = {"state": state, "per_page": 25}
        if search:
            params["search"] = search
        async with _client() as c:
            r = await c.get(f"/projects/{_encode(project)}/issues", params=params)
            r.raise_for_status()
            data = r.json()
        return {
            "issues": [
                {
                    "iid": i["iid"],
                    "title": i["title"],
                    "state": i["state"],
                    "assignees": [a["username"] for a in i.get("assignees", [])],
                    "labels": i.get("labels", []),
                    "web_url": i["web_url"],
                }
                for i in data
            ],
            "count": len(data),
        }

    async def create_issue(
        self,
        project: str,
        title: str,
        description: str = "",
        labels: str = "",
        assignees: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"title": title, "description": description}
        if labels:
            body["labels"] = labels
        if assignees:
            ids: list[int] = []
            async with _client() as c:
                for u in assignees:
                    r = await c.get("/users", params={"username": u})
                    r.raise_for_status()
                    users = r.json()
                    if users:
                        ids.append(users[0]["id"])
            body["assignee_ids"] = ids
        async with _client() as c:
            r = await c.post(f"/projects/{_encode(project)}/issues", json=body)
            r.raise_for_status()
            data = r.json()
        log.info("gitlab.create_issue", project=project, title=title)
        return {"iid": data["iid"], "title": data["title"], "web_url": data["web_url"], "status": "created"}

    async def update_issue(
        self,
        project: str,
        issue_iid: int,
        state_event: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if state_event:
            body["state_event"] = state_event
        if title:
            body["title"] = title
        if description:
            body["description"] = description
        async with _client() as c:
            r = await c.put(f"/projects/{_encode(project)}/issues/{issue_iid}", json=body)
            r.raise_for_status()
            data = r.json()
        return {"iid": data["iid"], "state": data["state"], "status": "updated"}

    async def get_pipeline(self, project: str, pipeline_id: int) -> dict:
        async with _client() as c:
            pr, jr = await _gather(
                c.get(f"/projects/{_encode(project)}/pipelines/{pipeline_id}"),
                c.get(f"/projects/{_encode(project)}/pipelines/{pipeline_id}/jobs", params={"per_page": 50}),
            )
        p = pr.json()
        return {
            "id": p["id"],
            "status": p["status"],
            "ref": p["ref"],
            "sha": p["sha"][:8],
            "duration": p.get("duration"),
            "web_url": p["web_url"],
            "jobs": [{"name": j["name"], "stage": j["stage"], "status": j["status"]} for j in jr.json()],
        }

    async def trigger_pipeline(self, project: str, ref: str, variables: list[dict] | None = None) -> dict:
        body: dict[str, Any] = {"ref": ref}
        if variables:
            body["variables"] = [{"key": v["key"], "value": v["value"], "variable_type": "env_var"} for v in variables]
        async with _client() as c:
            r = await c.post(f"/projects/{_encode(project)}/pipeline", json=body)
            r.raise_for_status()
            data = r.json()
        log.info("gitlab.trigger_pipeline", project=project, ref=ref)
        return {"id": data["id"], "status": data["status"], "ref": data["ref"]}

    async def create_branch(self, project: str, branch: str, ref: str = "main") -> dict:
        async with _client() as c:
            r = await c.post(f"/projects/{_encode(project)}/repository/branches", json={"branch": branch, "ref": ref})
            r.raise_for_status()
            data = r.json()
        return {"branch": data["name"], "commit": data["commit"]["short_id"], "status": "created"}

    async def add_member(self, project: str, username: str, access_level: int = 30) -> dict:
        async with _client() as c:
            ru = await c.get("/users", params={"username": username})
            ru.raise_for_status()
            users = ru.json()
            if not users:
                return {"error": f"User '{username}' not found"}
            r = await c.post(f"/projects/{_encode(project)}/members", json={"user_id": users[0]["id"], "access_level": access_level})
            r.raise_for_status()
        log.info("gitlab.add_member", project=project, username=username)
        return {"project": project, "username": username, "access_level": access_level, "status": "added"}


async def _gather(*coros: Any) -> tuple:
    import asyncio
    return tuple(await asyncio.gather(*coros))
