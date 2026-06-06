from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _headers() -> dict[str, str]:
    s = get_settings()
    return {"Authorization": f"Bearer {s.grafana_token}", "Content-Type": "application/json"}


class GrafanaTools:
    def _url(self) -> str:
        return get_settings().grafana_url.rstrip("/")

    async def list_dashboards(self, query: str = "") -> dict:
        params = {"type": "dash-db"}
        if query:
            params["query"] = query
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/search", headers=_headers(), params=params)
            r.raise_for_status()
            dashboards = r.json()
            return {
                "dashboards": [
                    {"title": d["title"], "uid": d["uid"], "url": f"{self._url()}{d['url']}"}
                    for d in dashboards
                ],
                "count": len(dashboards),
            }

    async def get_dashboard_url(self, uid: str, var_namespace: str | None = None, var_pod: str | None = None) -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/dashboards/uid/{uid}", headers=_headers())
            r.raise_for_status()
            dash = r.json()
            base_url = f"{self._url()}{dash['meta']['url']}"
            params = []
            if var_namespace:
                params.append(f"var-namespace={var_namespace}")
            if var_pod:
                params.append(f"var-pod={var_pod}")
            full_url = base_url + ("?" + "&".join(params) if params else "")
            return {"title": dash["dashboard"]["title"], "url": full_url}

    async def create_annotation(
        self,
        text: str,
        dashboard_id: int | None = None,
        panel_id: int | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        payload: dict = {
            "text": text,
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            "tags": tags or ["opsbot"],
        }
        if dashboard_id:
            payload["dashboardId"] = dashboard_id
        if panel_id:
            payload["panelId"] = panel_id
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{self._url()}/api/annotations", headers=_headers(), json=payload)
            r.raise_for_status()
            return {"annotation_id": r.json().get("id"), "status": "created"}

    async def list_alerts(self, state: str = "firing") -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/v1/provisioning/alert-rules", headers=_headers())
            r.raise_for_status()
            rules = r.json()
            return {"alert_rules": rules[:20], "count": len(rules)}
