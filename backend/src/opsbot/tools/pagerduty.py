from __future__ import annotations

import pdpyras
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _session() -> pdpyras.APISession:
    s = get_settings()
    return pdpyras.APISession(s.pagerduty_api_key, default_from=s.pagerduty_from_email)


class PagerDutyTools:
    def list_incidents(self, status: list[str] | None = None, limit: int = 20) -> dict:
        session = _session()
        statuses = status or ["triggered", "acknowledged"]
        incidents = list(session.list_all("incidents", params={"statuses[]": statuses, "limit": limit}))
        return {
            "incidents": [
                {
                    "id": i["id"],
                    "title": i["title"],
                    "status": i["status"],
                    "urgency": i["urgency"],
                    "service": i["service"]["summary"],
                    "created_at": i["created_at"],
                    "html_url": i["html_url"],
                }
                for i in incidents
            ],
            "count": len(incidents),
        }

    def get_oncall(self, escalation_policy_id: str | None = None) -> dict:
        session = _session()
        params = {}
        if escalation_policy_id:
            params["escalation_policy_ids[]"] = escalation_policy_id
        oncalls = list(session.list_all("oncalls", params=params))
        return {
            "oncalls": [
                {
                    "user": o["user"]["summary"],
                    "escalation_policy": o["escalation_policy"]["summary"],
                    "schedule": o.get("schedule", {}).get("summary"),
                    "escalation_level": o["escalation_level"],
                    "start": o.get("start"),
                    "end": o.get("end"),
                }
                for o in oncalls[:10]
            ]
        }

    def acknowledge_incident(self, incident_id: str) -> dict:
        session = _session()
        session.put(
            f"incidents/{incident_id}",
            json={"incident": {"type": "incident_reference", "status": "acknowledged"}},
        )
        log.info("pagerduty.acknowledge", incident=incident_id)
        return {"incident_id": incident_id, "status": "acknowledged"}

    def resolve_incident(self, incident_id: str) -> dict:
        session = _session()
        session.put(
            f"incidents/{incident_id}",
            json={"incident": {"type": "incident_reference", "status": "resolved"}},
        )
        log.info("pagerduty.resolve", incident=incident_id)
        return {"incident_id": incident_id, "status": "resolved"}

    def create_incident(self, title: str, service_id: str, urgency: str = "high", body: str = "") -> dict:
        session = _session()
        payload = {
            "incident": {
                "type": "incident",
                "title": title,
                "service": {"id": service_id, "type": "service_reference"},
                "urgency": urgency,
                "body": {"type": "incident_body", "details": body},
            }
        }
        result = session.post("incidents", json=payload)
        incident = result["incident"]
        return {"id": incident["id"], "url": incident["html_url"], "status": "created"}
