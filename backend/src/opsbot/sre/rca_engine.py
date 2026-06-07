from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from opsbot.agent.llm import LLMClient
from opsbot.agent.prompts.rca import RCA_ANALYSIS_PROMPT
from opsbot.tools.kubernetes import KubernetesTools
from opsbot.tools.prometheus import PrometheusTools

log = structlog.get_logger(__name__)


class RCAEngine:
    def __init__(self) -> None:
        self._llm = LLMClient()
        self._prometheus = PrometheusTools()
        self._k8s = KubernetesTools()

    async def analyze(
        self,
        incident_description: str,
        service_name: str | None = None,
        namespace: str = "default",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        log.info("rca.analyze.start", service=service_name, incident=incident_description[:100])

        now = datetime.now(UTC)
        end = end_time or now
        start = start_time or (end - timedelta(hours=3))

        # Gather evidence in parallel
        evidence_tasks = [
            self._gather_metrics(service_name, start, end),
            self._gather_k8s_events(namespace, start, end),
            self._gather_pod_logs(service_name, namespace, start, end),
            self._gather_recent_deployments(namespace),
        ]
        results = await asyncio.gather(*evidence_tasks, return_exceptions=True)

        metrics_data = results[0] if not isinstance(results[0], Exception) else {"error": str(results[0])}
        k8s_events = results[1] if not isinstance(results[1], Exception) else {"error": str(results[1])}
        pod_logs = results[2] if not isinstance(results[2], Exception) else {"error": str(results[2])}
        deployments = results[3] if not isinstance(results[3], Exception) else {"error": str(results[3])}

        prompt = RCA_ANALYSIS_PROMPT.format(
            incident_description=incident_description,
            pod_logs=self._truncate(json.dumps(pod_logs, indent=2), 3000),
            metrics=self._truncate(json.dumps(metrics_data, indent=2), 2000),
            k8s_events=self._truncate(json.dumps(k8s_events, indent=2), 2000),
            recent_deployments=self._truncate(json.dumps(deployments, indent=2), 1000),
            additional_context=f"Service: {service_name}, Namespace: {namespace}, Time range: {start.isoformat()} to {end.isoformat()}",
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            model="claude-sonnet-4-6",
        )

        try:
            content = response.content or "{}"
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            log.warning("rca.parse.failed")
            result = {
                "root_cause": "Unable to parse structured response",
                "confidence": 0.0,
                "summary": response.content,
                "contributing_factors": [],
                "evidence": {},
                "timeline": [],
                "remediation_steps": [],
                "recommended_actions": [],
            }

        result["service_name"] = service_name
        result["incident_description"] = incident_description
        result["analysis_period"] = {"start": start.isoformat(), "end": end.isoformat()}
        result["generated_at"] = now.isoformat()
        result["raw_evidence"] = {
            "metrics": metrics_data,
            "k8s_events": k8s_events,
            "pod_logs": pod_logs,
            "deployments": deployments,
        }

        log.info("rca.analyze.done", service=service_name, confidence=result.get("confidence", 0))
        return result

    async def _gather_metrics(self, service: str | None, start: datetime, end: datetime) -> dict:
        if not service:
            return {}
        try:
            error_rate = await self._prometheus.query_range(
                f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[1m])) / sum(rate(http_requests_total{{service="{service}"}}[1m]))',
                start=start.isoformat() + "Z",
                end=end.isoformat() + "Z",
                step="1m",
            )
            latency = await self._prometheus.query_range(
                f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{service="{service}"}}[1m])) by (le)) * 1000',
                start=start.isoformat() + "Z",
                end=end.isoformat() + "Z",
                step="1m",
            )
            memory = await self._prometheus.query_range(
                f'sum(container_memory_working_set_bytes{{namespace=~".*",container="{service}"}}) by (pod)',
                start=start.isoformat() + "Z",
                end=end.isoformat() + "Z",
                step="1m",
            )
            return {"error_rate": error_rate, "latency_p99_ms": latency, "memory_bytes": memory}
        except Exception as e:
            return {"error": str(e)}

    async def _gather_k8s_events(self, namespace: str, start: datetime, end: datetime) -> dict:
        try:
            return await self._k8s.list_events(namespace=namespace, field_selector="type=Warning")
        except Exception as e:
            return {"error": str(e)}

    async def _gather_pod_logs(self, service: str | None, namespace: str, start: datetime, end: datetime) -> dict:
        if not service:
            return {}
        try:
            pods_resp = await self._k8s.list_pods(namespace=namespace, label_selector=f"app={service}")
            pods = pods_resp.get("pods", [])
            if not pods:
                return {"message": f"No pods found for service {service} in {namespace}"}
            logs: dict[str, str] = {}
            for pod in pods[:3]:
                pod_name = pod["name"]
                try:
                    log_resp = await self._k8s.get_pod_logs(pod_name=pod_name, namespace=namespace, tail_lines=200)
                    logs[pod_name] = log_resp.get("logs", "")
                except Exception as e:
                    logs[pod_name] = f"Error: {e}"
            return {"pods": logs}
        except Exception as e:
            return {"error": str(e)}

    async def _gather_recent_deployments(self, namespace: str) -> dict:
        try:
            return await self._k8s.list_deployments(namespace=namespace)
        except Exception as e:
            return {"error": str(e)}

    def _truncate(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"
