from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)

# Common field names for log levels across different log shipping agents
LEVEL_FIELDS = ["log.level", "level", "severity", "loglevel"]
SERVICE_FIELDS = [
    "service.name", "app", "fields.service",
    "kubernetes.labels.app", "kubernetes.pod_name",
]


def _client() -> httpx.AsyncClient:
    s = get_settings()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if s.opensearch_api_key:
        headers["Authorization"] = f"ApiKey {s.opensearch_api_key}"
    elif s.opensearch_username and s.opensearch_password:
        creds = base64.b64encode(
            f"{s.opensearch_username}:{s.opensearch_password}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {creds}"
    return httpx.AsyncClient(
        base_url=s.opensearch_url,
        headers=headers,
        verify=s.opensearch_verify_ssl,
        timeout=30.0,
    )


def _service_filter(service: str) -> dict:
    return {
        "bool": {
            "should": [
                {"term": {"kubernetes.labels.app": service}},
                {"term": {"kubernetes.labels.app.keyword": service}},
                {"term": {"service.name": service}},
                {"term": {"service.name.keyword": service}},
                {"term": {"app": service}},
                {"wildcard": {"kubernetes.pod_name": {"value": f"{service}*"}}},
            ],
            "minimum_should_match": 1,
        }
    }


def _level_filter(levels: list[str]) -> dict:
    should: list[dict] = []
    for field in LEVEL_FIELDS:
        for lvl in levels:
            should.append({"term": {field: lvl}})
            should.append({"term": {f"{field}.keyword": lvl}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def _summarize_hits(hits: list[dict]) -> list[dict]:
    result = []
    for h in hits:
        s = h.get("_source", {})
        k8s = s.get("kubernetes", {})
        result.append({
            "timestamp": s.get("@timestamp") or s.get("timestamp", ""),
            "level": (
                s.get("log", {}).get("level")
                or s.get("level")
                or s.get("severity", "")
            ),
            "message": str(s.get("message") or s.get("msg", ""))[:500],
            "service": (
                s.get("service", {}).get("name")
                or s.get("app")
                or k8s.get("labels", {}).get("app", "")
            ),
            "pod": k8s.get("pod_name") or k8s.get("pod", {}).get("name", ""),
            "namespace": k8s.get("namespace") or k8s.get("namespace_name", ""),
        })
    return result


class OpenSearchTools:
    """Direct OpenSearch/Elasticsearch tool implementations."""

    def _index(self, index: str | None = None) -> str:
        return index or get_settings().opensearch_default_index

    async def search_logs(
        self,
        query: str = "",
        service: str = "",
        index: str | None = None,
        lookback: str = "1h",
        level: str = "all",
        size: int = 50,
    ) -> dict:
        must: list[dict] = [{"range": {"@timestamp": {"gte": f"now-{lookback}"}}}]
        if query:
            must.append({
                "multi_match": {
                    "query": query,
                    "fields": ["message", "msg", "error.message"],
                    "type": "phrase_prefix",
                }
            })

        filters: list[dict] = []
        if service:
            filters.append(_service_filter(service))
        if level != "all":
            filters.append(_level_filter([level]))

        body: dict[str, Any] = {
            "query": {"bool": {"must": must, "filter": filters}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": min(size, 200),
            "_source": [
                "@timestamp", "message", "msg",
                "log.level", "level", "severity",
                "service.name", "app",
                "kubernetes.pod_name", "kubernetes.namespace",
                "kubernetes.labels.app",
            ],
        }

        async with _client() as c:
            r = await c.post(f"/{self._index(index)}/_search", json=body)
            r.raise_for_status()
            data = r.json()

        hits = data.get("hits", {}).get("hits", [])
        return {
            "total_matched": data.get("hits", {}).get("total", {}).get("value", len(hits)),
            "returned": len(hits),
            "time_range": f"last {lookback}",
            "logs": _summarize_hits(hits),
        }

    async def get_error_summary(
        self,
        service: str = "",
        query: str = "",
        index: str | None = None,
        lookback: str = "1h",
        top_n: int = 20,
    ) -> dict:
        must: list[dict] = [{"range": {"@timestamp": {"gte": f"now-{lookback}"}}}]
        if query:
            must.append({"multi_match": {"query": query, "fields": ["message", "error.message"]}})

        error_filter: dict = {
            "bool": {
                "should": [
                    *[{"term": {f: v}} for f in LEVEL_FIELDS for v in ["error", "fatal", "warn", "ERROR", "FATAL"]],
                    {"match": {"message": "exception"}},
                    {"match": {"message": "timeout"}},
                    {"match": {"message": "failed"}},
                    {"match": {"message": "error"}},
                ],
                "minimum_should_match": 1,
            }
        }
        filters: list[dict] = [error_filter]
        if service:
            filters.append(_service_filter(service))

        interval = "1h" if lookback.endswith("d") else "5m"
        body: dict[str, Any] = {
            "query": {"bool": {"must": must, "filter": filters}},
            "size": 10,
            "sort": [{"@timestamp": {"order": "desc"}}],
            "_source": ["@timestamp", "message", "log.level", "level", "kubernetes.pod_name", "service.name"],
            "aggs": {
                "top_errors": {
                    "terms": {"field": "message.keyword", "size": top_n, "missing": "(no message)"}
                },
                "error_levels": {"terms": {"field": "log.level.keyword", "size": 10}},
                "errors_over_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": interval,
                        "min_doc_count": 1,
                    }
                },
                "top_services": {
                    "terms": {"field": "service.name.keyword", "size": 10, "missing": "(unknown)"}
                },
            },
        }

        async with _client() as c:
            r = await c.post(f"/{self._index(index)}/_search", json=body)
            r.raise_for_status()
            data = r.json()

        aggs = data.get("aggregations", {})
        return {
            "total_errors": data.get("hits", {}).get("total", {}).get("value", 0),
            "time_range": f"last {lookback}",
            "top_error_messages": [
                {"message": b["key"], "count": b["doc_count"]}
                for b in aggs.get("top_errors", {}).get("buckets", [])
            ],
            "error_level_breakdown": [
                {"level": b["key"], "count": b["doc_count"]}
                for b in aggs.get("error_levels", {}).get("buckets", [])
            ],
            "errors_over_time": [
                {"time": b["key_as_string"], "count": b["doc_count"]}
                for b in aggs.get("errors_over_time", {}).get("buckets", [])
            ],
            "top_services_with_errors": [
                {"service": b["key"], "count": b["doc_count"]}
                for b in aggs.get("top_services", {}).get("buckets", [])
            ],
            "sample_recent_errors": _summarize_hits(data.get("hits", {}).get("hits", [])),
        }

    async def count_events(
        self,
        query: str,
        service: str = "",
        index: str | None = None,
        lookback: str = "1h",
        level: str = "all",
    ) -> dict:
        must: list[dict] = [
            {"range": {"@timestamp": {"gte": f"now-{lookback}"}}},
            {"multi_match": {"query": query, "fields": ["message", "msg", "error.message"]}},
        ]
        filters: list[dict] = []
        if service:
            filters.append(_service_filter(service))
        if level != "all":
            filters.append(_level_filter([level]))

        body: dict[str, Any] = {
            "query": {"bool": {"must": must, "filter": filters}},
            "size": 0,
            "aggs": {
                "over_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": "5m",
                        "min_doc_count": 1,
                    }
                }
            },
        }

        async with _client() as c:
            r = await c.post(f"/{self._index(index)}/_search", json=body)
            r.raise_for_status()
            data = r.json()

        return {
            "count": data.get("hits", {}).get("total", {}).get("value", 0),
            "time_range": f"last {lookback}",
            "query": query,
            "service": service or "all",
            "per_5min_breakdown": [
                {"time": b["key_as_string"], "count": b["doc_count"]}
                for b in data.get("aggregations", {}).get("over_time", {}).get("buckets", [])
            ],
        }

    async def search_slow_queries(
        self,
        service: str = "",
        index: str | None = None,
        lookback: str = "1h",
        min_duration_ms: int | None = None,
        size: int = 50,
    ) -> dict:
        slow_patterns = [
            "timeout", "timed out", "deadline exceeded",
            "slow query", "slow request", "ETIMEDOUT",
            "connection timeout", "read timeout", "write timeout",
            "504", "408", "context deadline",
        ]
        must: list[dict] = [
            {"range": {"@timestamp": {"gte": f"now-{lookback}"}}},
            {
                "bool": {
                    "should": [{"match_phrase": {"message": p}} for p in slow_patterns],
                    "minimum_should_match": 1,
                }
            },
        ]

        filters: list[dict] = []
        if service:
            filters.append(_service_filter(service))
        if min_duration_ms is not None:
            filters.append({
                "bool": {
                    "should": [
                        {"range": {"duration_ms": {"gte": min_duration_ms}}},
                        {"range": {"duration": {"gte": min_duration_ms}}},
                        {"range": {"took": {"gte": min_duration_ms}}},
                    ],
                    "minimum_should_match": 1,
                }
            })

        body: dict[str, Any] = {
            "query": {"bool": {"must": must, "filter": filters}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": min(size, 200),
            "_source": [
                "@timestamp", "message", "log.level", "level",
                "service.name", "kubernetes.pod_name", "kubernetes.namespace",
                "duration", "duration_ms", "took", "elapsed",
                "db.statement", "http.url",
            ],
            "aggs": {
                "by_service": {
                    "terms": {"field": "service.name.keyword", "size": 10, "missing": "(unknown)"}
                },
                "count_over_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": "5m",
                        "min_doc_count": 1,
                    }
                },
            },
        }

        async with _client() as c:
            r = await c.post(f"/{self._index(index)}/_search", json=body)
            r.raise_for_status()
            data = r.json()

        hits = data.get("hits", {}).get("hits", [])
        aggs = data.get("aggregations", {})
        return {
            "total_slow_timeout_events": data.get("hits", {}).get("total", {}).get("value", len(hits)),
            "time_range": f"last {lookback}",
            "by_service": [
                {"service": b["key"], "count": b["doc_count"]}
                for b in aggs.get("by_service", {}).get("buckets", [])
            ],
            "count_over_time": [
                {"time": b["key_as_string"], "count": b["doc_count"]}
                for b in aggs.get("count_over_time", {}).get("buckets", [])
            ],
            "events": _summarize_hits(hits),
        }

    async def list_indices(self, pattern: str = "*") -> dict:
        async with _client() as c:
            r = await c.get(
                f"/_cat/indices/{pattern}",
                params={"format": "json", "h": "index,health,status,docs.count,store.size", "s": "index"},
            )
            r.raise_for_status()
            raw = r.json()

        indices = [
            {
                "name": i.get("index"),
                "health": i.get("health"),
                "docs": i.get("docs.count"),
                "size": i.get("store.size"),
            }
            for i in (raw if isinstance(raw, list) else [])
            if not str(i.get("index", "")).startswith(".")
        ]
        return {"indices": indices[:50], "total": len(indices)}
