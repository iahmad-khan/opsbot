from __future__ import annotations

import base64

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _client() -> httpx.AsyncClient:
    s = get_settings()
    creds = base64.b64encode(f"{s.confluence_username}:{s.confluence_api_token}".encode()).decode()
    return httpx.AsyncClient(
        base_url=f"{s.confluence_url.rstrip('/')}/rest/api",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Atlassian-Token": "no-check",
        },
        timeout=30.0,
    )


def _text_to_storage(text: str) -> str:
    """Convert plain text / simple markdown to Confluence storage format."""
    if text.strip().startswith("<"):
        return text
    parts = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if para.startswith("## "):
            parts.append(f"<h2>{para[3:]}</h2>")
        elif para.startswith("# "):
            parts.append(f"<h1>{para[2:]}</h1>")
        elif para.startswith("### "):
            parts.append(f"<h3>{para[4:]}</h3>")
        elif para.startswith(("- ", "* ")):
            items = "".join(f"<li>{line.lstrip('*-').strip()}</li>" for line in para.split("\n") if line.strip())
            parts.append(f"<ul>{items}</ul>")
        else:
            parts.append(f"<p>{para.replace(chr(10), '<br/>')}</p>")
    return "\n".join(parts)


class ConfluenceTools:
    def _space(self, space_key: str | None) -> str:
        return space_key or get_settings().confluence_default_space

    async def search_pages(self, query: str, space_key: str | None = None, max_results: int = 20) -> dict:
        cql = query
        if not any(op in cql for op in ("=", "~", " AND ", " OR ")):
            cql = f'text~"{cql}"'
        if space_key:
            cql = f'space="{space_key}" AND ({cql})'
        async with _client() as c:
            r = await c.get("/content/search", params={"cql": cql, "limit": max_results, "expand": "space,version"})
            r.raise_for_status()
            data = r.json()
        s = get_settings()
        pages = [
            {
                "id": p["id"],
                "title": p["title"],
                "space": p.get("space", {}).get("key"),
                "last_updated": p.get("version", {}).get("when"),
                "url": f"{s.confluence_url}{p.get('_links', {}).get('webui', '')}",
            }
            for p in data.get("results", [])
        ]
        return {"total": data.get("totalSize", len(pages)), "pages": pages}

    async def get_page(self, page_id: str | None = None, title: str | None = None, space_key: str | None = None) -> dict:
        async with _client() as c:
            if page_id:
                r = await c.get(f"/content/{page_id}", params={"expand": "body.storage,version,space"})
                r.raise_for_status()
                page = r.json()
            elif title:
                r = await c.get("/content", params={"spaceKey": self._space(space_key), "title": title, "expand": "body.storage,version", "limit": 1})
                r.raise_for_status()
                results = r.json().get("results", [])
                if not results:
                    return {"error": f"Page '{title}' not found"}
                page = results[0]
            else:
                return {"error": "Provide page_id or title"}
        s = get_settings()
        raw_body = page.get("body", {}).get("storage", {}).get("value", "")
        # Strip HTML tags for readable preview
        import re
        body_preview = re.sub(r"<[^>]+>", " ", raw_body).strip()[:2000]
        return {
            "id": page["id"],
            "title": page["title"],
            "space": page.get("space", {}).get("key"),
            "version": page.get("version", {}).get("number"),
            "last_updated": page.get("version", {}).get("when"),
            "by": page.get("version", {}).get("by", {}).get("displayName"),
            "url": f"{s.confluence_url}{page.get('_links', {}).get('webui', '')}",
            "body_preview": body_preview,
        }

    async def create_page(
        self,
        title: str,
        content: str,
        space_key: str | None = None,
        parent_id: str | None = None,
        parent_title: str | None = None,
    ) -> dict:
        sk = self._space(space_key)
        if not sk:
            return {"error": "space_key is required"}
        body: dict = {
            "type": "page",
            "title": title,
            "space": {"key": sk},
            "body": {"storage": {"value": _text_to_storage(content), "representation": "storage"}},
        }
        async with _client() as c:
            if parent_id:
                body["ancestors"] = [{"id": parent_id}]
            elif parent_title:
                rp = await c.get("/content", params={"spaceKey": sk, "title": parent_title, "limit": 1})
                rp.raise_for_status()
                results = rp.json().get("results", [])
                if results:
                    body["ancestors"] = [{"id": results[0]["id"]}]
            r = await c.post("/content", json=body)
            r.raise_for_status()
            data = r.json()
        s = get_settings()
        log.info("confluence.create_page", title=title, space=sk)
        url = f"{s.confluence_url}{data.get('_links', {}).get('webui', '')}"
        return {"id": data["id"], "title": data["title"], "url": url, "status": "created"}

    async def update_page(
        self,
        page_id: str,
        title: str,
        content: str,
        version_comment: str = "",
    ) -> dict:
        async with _client() as c:
            rcurr = await c.get(f"/content/{page_id}", params={"expand": "version"})
            rcurr.raise_for_status()
            current = rcurr.json()
            new_version = (current.get("version", {}).get("number", 0)) + 1
            body: dict = {
                "type": "page",
                "title": title,
                "version": {"number": new_version},
                "body": {"storage": {"value": _text_to_storage(content), "representation": "storage"}},
            }
            if version_comment:
                body["version"]["message"] = version_comment  # type: ignore[index]
            r = await c.put(f"/content/{page_id}", json=body)
            r.raise_for_status()
            data = r.json()
        s = get_settings()
        log.info("confluence.update_page", page_id=page_id, version=new_version)
        return {"id": data["id"], "title": data["title"], "version": new_version, "url": f"{s.confluence_url}{data.get('_links', {}).get('webui', '')}", "status": "updated"}

    async def append_to_page(self, page_id: str, content_to_append: str, version_comment: str = "") -> dict:
        async with _client() as c:
            rcurr = await c.get(f"/content/{page_id}", params={"expand": "body.storage,version"})
            rcurr.raise_for_status()
            current = rcurr.json()
            existing = current.get("body", {}).get("storage", {}).get("value", "")
            new_content = existing + "\n" + _text_to_storage(content_to_append)
            new_version = (current.get("version", {}).get("number", 0)) + 1
            body: dict = {
                "type": "page",
                "title": current["title"],
                "version": {"number": new_version},
                "body": {"storage": {"value": new_content, "representation": "storage"}},
            }
            if version_comment:
                body["version"]["message"] = version_comment  # type: ignore[index]
            r = await c.put(f"/content/{page_id}", json=body)
            r.raise_for_status()
        return {"page_id": page_id, "title": current["title"], "status": "appended"}

    async def add_comment(self, page_id: str, comment: str) -> dict:
        async with _client() as c:
            r = await c.post("/content", json={
                "type": "comment",
                "container": {"id": page_id, "type": "page"},
                "body": {"storage": {"value": _text_to_storage(comment), "representation": "storage"}},
            })
            r.raise_for_status()
        return {"page_id": page_id, "status": "comment_added"}

    async def list_spaces(self, space_type: str = "global") -> dict:
        params: dict = {"limit": 50}
        if space_type != "all":
            params["type"] = space_type
        async with _client() as c:
            r = await c.get("/space", params=params)
            r.raise_for_status()
            data = r.json()
        s = get_settings()
        spaces = [
            {"key": sp["key"], "name": sp["name"], "type": sp.get("type"), "url": f"{s.confluence_url}{sp.get('_links', {}).get('webui', '')}"}
            for sp in data.get("results", [])
        ]
        return {"spaces": spaces, "count": len(spaces)}
