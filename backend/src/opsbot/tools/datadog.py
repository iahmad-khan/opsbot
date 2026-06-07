from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v1.api.metrics_api import MetricsApi
from datadog_api_client.v1.api.monitors_api import MonitorsApi
from datadog_api_client.v2.api.logs_api import LogsApi

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


def _config() -> Configuration:
    s = get_settings()
    cfg = Configuration()
    cfg.api_key["apiKeyAuth"] = s.datadog_api_key
    cfg.api_key["appKeyAuth"] = s.datadog_app_key
    cfg.server_variables["site"] = s.datadog_site
    return cfg


class DatadogTools:
    def query_metrics(self, query: str, from_ts: int | None = None, to_ts: int | None = None) -> dict:
        now = int(datetime.now(UTC).timestamp())
        with ApiClient(_config()) as api_client:
            api = MetricsApi(api_client)
            result = api.query_metrics(
                _from=from_ts or now - 3600,
                to=to_ts or now,
                query=query,
            )
            series = []
            for s in result.series or []:
                series.append({
                    "metric": s.metric,
                    "display_name": s.display_name,
                    "pointlist": [[p[0], p[1]] for p in (s.pointlist or [])[-20:]],
                })
            return {"query": query, "series": series}

    async def get_logs(
        self,
        query: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 50,
    ) -> dict:
        from datadog_api_client.v2.model.logs_list_request import LogsListRequest
        from datadog_api_client.v2.model.logs_list_request_page import LogsListRequestPage
        from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter
        from datadog_api_client.v2.model.logs_sort import LogsSort

        now = datetime.now(UTC)
        body = LogsListRequest(
            filter=LogsQueryFilter(
                query=query,
                _from=from_ts or (now - timedelta(hours=1)).isoformat(),
                to=to_ts or now.isoformat(),
            ),
            sort=LogsSort.TIMESTAMP_DESCENDING,
            page=LogsListRequestPage(limit=limit),
        )
        with ApiClient(_config()) as api_client:
            api = LogsApi(api_client)
            result = api.list_logs(body=body)
            logs = []
            for log_entry in result.data or []:
                attrs = log_entry.attributes
                logs.append({
                    "timestamp": str(attrs.timestamp) if attrs else None,
                    "message": attrs.message if attrs else None,
                    "service": attrs.service if attrs else None,
                    "status": attrs.status if attrs else None,
                })
            return {"query": query, "logs": logs, "count": len(logs)}

    def list_monitors(self, tags: list[str] | None = None, monitor_type: str | None = None) -> dict:
        with ApiClient(_config()) as api_client:
            api = MonitorsApi(api_client)
            kwargs: dict[str, Any] = {}
            if tags:
                kwargs["monitor_tags"] = ",".join(tags)
            monitors = api.list_monitors(**kwargs)
            return {
                "monitors": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "type": str(m.type),
                        "overall_state": str(m.overall_state) if m.overall_state else None,
                        "query": m.query,
                    }
                    for m in (monitors or [])
                ],
                "count": len(monitors or []),
            }

    def get_monitor(self, monitor_id: int) -> dict:
        with ApiClient(_config()) as api_client:
            api = MonitorsApi(api_client)
            m = api.get_monitor(monitor_id)
            return {
                "id": m.id,
                "name": m.name,
                "type": str(m.type),
                "query": m.query,
                "overall_state": str(m.overall_state) if m.overall_state else None,
                "message": m.message,
                "tags": list(m.tags or []),
            }
