from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


class PrometheusTools:
    def _url(self) -> str:
        return get_settings().prometheus_url.rstrip("/")

    async def query(self, promql: str, time: str | None = None) -> dict:
        params: dict[str, Any] = {"query": promql}
        if time:
            params["time"] = time
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/v1/query", params=params)
            r.raise_for_status()
            data = r.json()
            return {"query": promql, "result": data.get("data", {}), "status": data.get("status")}

    async def query_range(
        self,
        promql: str,
        start: str | None = None,
        end: str | None = None,
        step: str = "60s",
        lookback_hours: int = 24,
    ) -> dict:
        now = datetime.utcnow()
        params: dict[str, Any] = {
            "query": promql,
            "start": start or (now - timedelta(hours=lookback_hours)).isoformat() + "Z",
            "end": end or now.isoformat() + "Z",
            "step": step,
        }
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/v1/query_range", params=params)
            r.raise_for_status()
            data = r.json()
            return {"query": promql, "result": data.get("data", {}), "status": data.get("status")}

    async def list_alerts(self, state: str = "firing") -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/v1/alerts")
            r.raise_for_status()
            alerts = r.json().get("data", {}).get("alerts", [])
            if state != "all":
                alerts = [a for a in alerts if a.get("state") == state]
            return {
                "alerts": [
                    {
                        "name": a["labels"].get("alertname"),
                        "state": a["state"],
                        "severity": a["labels"].get("severity"),
                        "summary": a["annotations"].get("summary", ""),
                        "labels": a["labels"],
                        "active_since": a.get("activeAt"),
                    }
                    for a in alerts
                ],
                "count": len(alerts),
            }

    async def list_targets(self, state: str = "active") -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/v1/targets")
            r.raise_for_status()
            data = r.json().get("data", {})
            targets = data.get("activeTargets" if state == "active" else "droppedTargets", [])
            return {
                "targets": [
                    {
                        "job": t["labels"].get("job"),
                        "instance": t["labels"].get("instance"),
                        "health": t.get("health"),
                        "last_scrape": t.get("lastScrape"),
                        "labels": t.get("labels", {}),
                    }
                    for t in targets
                ],
                "count": len(targets),
            }

    async def get_rules(self) -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._url()}/api/v1/rules")
            r.raise_for_status()
            groups = r.json().get("data", {}).get("groups", [])
            rules = []
            for group in groups:
                for rule in group.get("rules", []):
                    rules.append({
                        "name": rule.get("name"),
                        "type": rule.get("type"),
                        "query": rule.get("query", rule.get("expr")),
                        "group": group.get("name"),
                        "state": rule.get("state"),
                    })
            return {"rules": rules, "count": len(rules)}

    async def silence_alert(
        self,
        matchers: list[dict],
        duration_hours: int = 1,
        comment: str = "Silenced by OpsBot",
        author: str = "opsbot",
    ) -> dict:
        from datetime import timezone
        now = datetime.now(timezone.utc)
        payload = {
            "matchers": matchers,
            "startsAt": now.isoformat(),
            "endsAt": (now + timedelta(hours=duration_hours)).isoformat(),
            "comment": comment,
            "createdBy": author,
        }
        alertmanager_url = get_settings().prometheus_url.replace("9090", "9093")
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{alertmanager_url}/api/v2/silences", json=payload)
            r.raise_for_status()
            silence_id = r.json().get("silenceID")
            return {"silence_id": silence_id, "duration_hours": duration_hours, "status": "silenced"}
