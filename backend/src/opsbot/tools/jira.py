from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _client() -> httpx.AsyncClient:
    s = get_settings()
    creds = base64.b64encode(f"{s.jira_username}:{s.jira_api_token}".encode()).decode()
    return httpx.AsyncClient(
        # API v2 — works on both Cloud (email:api_token) and Server (user:pass/PAT)
        base_url=f"{s.jira_url.rstrip('/')}/rest/api/2",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30.0,
    )


class JiraTools:
    async def search_issues(self, jql: str, max_results: int = 25) -> dict:
        async with _client() as c:
            r = await c.get(
                "/search",
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "fields": "summary,status,assignee,priority,issuetype,labels,updated,description",
                },
            )
            r.raise_for_status()
            data = r.json()
        s = get_settings()
        issues = [
            {
                "key": i["key"],
                "summary": i["fields"]["summary"],
                "status": i["fields"]["status"]["name"],
                "assignee": (i["fields"].get("assignee") or {}).get("displayName"),
                "priority": (i["fields"].get("priority") or {}).get("name"),
                "issue_type": i["fields"]["issuetype"]["name"],
                "labels": i["fields"].get("labels", []),
                "url": f"{s.jira_url}/browse/{i['key']}",
            }
            for i in data.get("issues", [])
        ]
        return {"total": data.get("total", 0), "issues": issues}

    async def get_issue(self, issue_key: str) -> dict:
        async with _client() as c:
            r = await c.get(f"/issue/{issue_key}")
            r.raise_for_status()
            data = r.json()
        s = get_settings()
        fields = data["fields"]
        comments = [
            {"author": c_["author"]["displayName"], "body": c_["body"][:500], "created": c_["created"]}
            for c_ in (fields.get("comment", {}).get("comments", []))[-5:]
        ]
        return {
            "key": data["key"],
            "summary": fields["summary"],
            "status": fields["status"]["name"],
            "issue_type": fields["issuetype"]["name"],
            "priority": (fields.get("priority") or {}).get("name"),
            "assignee": (fields.get("assignee") or {}).get("displayName"),
            "reporter": (fields.get("reporter") or {}).get("displayName"),
            "description": (fields.get("description") or "")[:1000],
            "labels": fields.get("labels", []),
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "recent_comments": comments,
            "url": f"{s.jira_url}/browse/{data['key']}",
        }

    async def create_issue(
        self,
        summary: str,
        description: str = "",
        project_key: str = "",
        issue_type: str = "Task",
        priority: str = "Medium",
        assignee: str = "",
        labels: list[str] | None = None,
    ) -> dict:
        s = get_settings()
        proj = project_key or s.jira_default_project
        if not proj:
            return {"error": "project_key is required"}
        fields: dict[str, Any] = {
            "project": {"key": proj},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }
        if description:
            fields["description"] = description
        if assignee:
            fields["assignee"] = {"name": assignee}
        if labels:
            fields["labels"] = labels
        async with _client() as c:
            r = await c.post("/issue", json={"fields": fields})
            r.raise_for_status()
            data = r.json()
        log.info("jira.create_issue", key=data["key"])
        return {"key": data["key"], "url": f"{s.jira_url}/browse/{data['key']}", "status": "created"}

    async def add_comment(self, issue_key: str, body: str) -> dict:
        async with _client() as c:
            r = await c.post(f"/issue/{issue_key}/comment", json={"body": body})
            r.raise_for_status()
        log.info("jira.add_comment", issue=issue_key)
        return {"issue": issue_key, "status": "comment_added"}

    async def transition_issue(self, issue_key: str, transition_name: str, comment: str = "") -> dict:
        async with _client() as c:
            rt = await c.get(f"/issue/{issue_key}/transitions")
            rt.raise_for_status()
            transitions = rt.json().get("transitions", [])
            match = next(
                (t for t in transitions if transition_name.lower() in t["name"].lower() or
                 transition_name.lower() in (t.get("to", {}).get("name", "")).lower()),
                None,
            )
            if not match:
                available = ", ".join(t["name"] for t in transitions)
                return {"error": f"Transition '{transition_name}' not found. Available: {available}"}
            body: dict[str, Any] = {"transition": {"id": match["id"]}}
            if comment:
                body["update"] = {"comment": [{"add": {"body": comment}}]}
            r = await c.post(f"/issue/{issue_key}/transitions", json=body)
            r.raise_for_status()
        log.info("jira.transition", issue=issue_key, to=match["to"]["name"])
        return {"issue": issue_key, "transitioned_to": match["to"]["name"], "status": "transitioned"}

    async def assign_issue(self, issue_key: str, username: str) -> dict:
        assignee: dict | None = None if username == "-1" else {"name": username}
        async with _client() as c:
            r = await c.put(f"/issue/{issue_key}/assignee", json=assignee)
            r.raise_for_status()
        return {"issue": issue_key, "assignee": username, "status": "assigned"}

    async def list_projects(self) -> dict:
        async with _client() as c:
            r = await c.get("/project", params={"maxResults": 50})
            r.raise_for_status()
            data = r.json()
        projects = [{"key": p["key"], "name": p["name"], "type": p.get("projectTypeKey")} for p in (data if isinstance(data, list) else data.get("values", []))]
        return {"projects": projects, "count": len(projects)}

    async def search_users(self, query: str) -> list[dict]:
        async with _client() as c:
            r = await c.get("/user/search", params={"query": query, "maxResults": 10})
            r.raise_for_status()
            data = r.json()
        return [
            {"account_id": u.get("accountId") or u.get("name"), "display_name": u.get("displayName"), "email": u.get("emailAddress")}
            for u in (data if isinstance(data, list) else [])
        ]

    async def link_issues(self, inward_issue: str, outward_issue: str, link_type: str = "relates to") -> dict:
        async with _client() as c:
            rlt = await c.get("/issueLinkType")
            rlt.raise_for_status()
            link_types = rlt.json().get("issueLinkTypes", [])
            match = next(
                (lt for lt in link_types if
                 link_type.lower() in lt["name"].lower() or
                 link_type.lower() in lt.get("inward", "").lower() or
                 link_type.lower() in lt.get("outward", "").lower()),
                link_types[0] if link_types else None,
            )
            r = await c.post("/issueLink", json={
                "type": {"name": match["name"] if match else "Relates"},
                "inwardIssue": {"key": inward_issue},
                "outwardIssue": {"key": outward_issue},
            })
            r.raise_for_status()
        return {"inward": inward_issue, "outward": outward_issue, "link_type": match["name"] if match else "Relates", "status": "linked"}
