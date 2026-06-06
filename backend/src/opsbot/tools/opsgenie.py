from __future__ import annotations

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"GenieKey {get_settings().opsgenie_api_key}",
        "Content-Type": "application/json",
    }

BASE = "https://api.opsgenie.com/v2"


class OpsGenieTools:
    async def list_alerts(self, status: str = "open", limit: int = 20) -> dict:
        params = {"limit": limit, "status": status, "order": "desc"}
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE}/alerts", headers=_headers(), params=params)
            r.raise_for_status()
            alerts = r.json().get("data", [])
            return {
                "alerts": [
                    {
                        "id": a["id"],
                        "message": a["message"],
                        "status": a["status"],
                        "priority": a["priority"],
                        "source": a.get("source"),
                        "created_at": a.get("createdAt"),
                        "tags": a.get("tags", []),
                    }
                    for a in alerts
                ],
                "count": len(alerts),
            }

    async def get_oncall(self, schedule_name: str) -> dict:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{BASE}/schedules/{schedule_name}/on-calls", headers=_headers())
            r.raise_for_status()
            data = r.json().get("data", {})
            return {
                "schedule": schedule_name,
                "oncall_participants": data.get("onCallParticipants", []),
                "start": data.get("startDate"),
                "end": data.get("endDate"),
            }

    async def acknowledge_alert(self, alert_id: str, note: str = "Acknowledged by OpsBot") -> dict:
        payload = {"note": note}
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{BASE}/alerts/{alert_id}/acknowledge", headers=_headers(), json=payload)
            r.raise_for_status()
            return {"alert_id": alert_id, "status": "acknowledged"}

    async def close_alert(self, alert_id: str, note: str = "Closed by OpsBot") -> dict:
        payload = {"note": note}
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{BASE}/alerts/{alert_id}/close", headers=_headers(), json=payload)
            r.raise_for_status()
            return {"alert_id": alert_id, "status": "closed"}

    async def create_alert(
        self,
        message: str,
        priority: str = "P3",
        tags: list[str] | None = None,
        description: str = "",
    ) -> dict:
        payload = {
            "message": message,
            "priority": priority,
            "tags": tags or ["opsbot"],
            "description": description,
            "source": "OpsBot",
        }
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{BASE}/alerts", headers=_headers(), json=payload)
            r.raise_for_status()
            return {"request_id": r.json().get("requestId"), "status": "created"}
