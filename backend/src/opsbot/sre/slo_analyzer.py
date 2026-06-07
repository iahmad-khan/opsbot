from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from opsbot.agent.llm import LLMClient
from opsbot.agent.prompts.rca import SLO_ANALYSIS_PROMPT
from opsbot.tools.prometheus import PrometheusTools

log = structlog.get_logger(__name__)

SLO_YAML_TEMPLATE = """\
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: slo-{service_name}
  namespace: {namespace}
  labels:
    app: {service_name}
    prometheus: kube-prometheus
    role: alert-rules
spec:
  groups:
  - name: slo.{service_name}.rules
    rules:
    # Availability SLI: ratio of successful requests
    - record: slo:availability:ratio_rate5m
      expr: |
        sum(rate(http_requests_total{{service="{service_name}",status!~"5.."}}[5m]))
        /
        sum(rate(http_requests_total{{service="{service_name}"}}[5m]))
      labels:
        service: {service_name}

    # Latency SLI: p99 < {latency_target_ms}ms
    - record: slo:latency_p99:seconds
      expr: |
        histogram_quantile(0.99,
          sum(rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) by (le)
        )
      labels:
        service: {service_name}

    # Availability SLO alert (burn rate 1h window)
    - alert: SLOAvailabilityFastBurn
      expr: |
        (
          1 - slo:availability:ratio_rate5m{{service="{service_name}"}}
        ) > ({error_budget_fraction} * 14.4)
      for: 1m
      labels:
        severity: critical
        service: {service_name}
      annotations:
        summary: "SLO burn rate critical for {service_name}"
        description: "Error rate is consuming error budget 14x faster than sustainable"

    - alert: SLOAvailabilitySlowBurn
      expr: |
        (
          1 - slo:availability:ratio_rate5m{{service="{service_name}"}}
        ) > ({error_budget_fraction} * 1)
      for: 1h
      labels:
        severity: warning
        service: {service_name}
      annotations:
        summary: "SLO burn rate elevated for {service_name}"
        description: "Consuming error budget faster than sustainable over 1h window"
"""


class SLOAnalyzer:
    def __init__(self) -> None:
        self._prometheus = PrometheusTools()
        self._llm = LLMClient()

    async def analyze(
        self,
        service_name: str,
        namespace: str = "default",
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        log.info("slo.analyze.start", service=service_name, lookback_days=lookback_days)

        # Gather metrics from Prometheus
        error_rate_data = await self._get_error_rate(service_name, lookback_days)
        latency_data = await self._get_latency(service_name, lookback_days)
        availability_data = await self._get_availability(service_name, lookback_days)
        request_volume_data = await self._get_request_volume(service_name, lookback_days)

        prompt = SLO_ANALYSIS_PROMPT.format(
            service_name=service_name,
            lookback_days=lookback_days,
            error_rate_data=json.dumps(error_rate_data, indent=2)[:2000],
            latency_data=json.dumps(latency_data, indent=2)[:2000],
            availability_data=json.dumps(availability_data, indent=2)[:2000],
            request_volume_data=json.dumps(request_volume_data, indent=2)[:1000],
        )

        response = await self._llm.complete(
            messages=[{"role": "user", "content": prompt}],
            model="claude-sonnet-4-6",
        )

        try:
            content = response.content or "{}"
            # extract JSON from response (handle markdown code blocks)
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            log.warning("slo.parse.failed", service=service_name)
            result = {"analysis_summary": response.content, "proposed_slos": []}

        # Generate YAML if we have enough data
        slos = result.get("proposed_slos", [])
        if slos:
            availability_slo = next((s for s in slos if s.get("name") == "availability"), slos[0])
            target = float(availability_slo.get("target", 0.999))
            error_budget = round(1 - target, 6)
            result["slo_yaml"] = SLO_YAML_TEMPLATE.format(
                service_name=service_name,
                namespace=namespace,
                error_budget_fraction=error_budget,
                latency_target_ms=availability_slo.get("p99_ms", 200),
            )

        result["service_name"] = service_name
        result["generated_at"] = datetime.now(UTC).isoformat()
        log.info("slo.analyze.done", service=service_name)
        return result

    async def _get_error_rate(self, service: str, lookback_days: int) -> dict:
        try:
            return await self._prometheus.query_range(
                f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[5m])) / sum(rate(http_requests_total{{service="{service}"}}[5m]))',
                lookback_hours=lookback_days * 24,
                step="1h",
            )
        except Exception as e:
            return {"error": str(e)}

    async def _get_latency(self, service: str, lookback_days: int) -> dict:
        try:
            return await self._prometheus.query_range(
                f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m])) by (le)) * 1000',
                lookback_hours=lookback_days * 24,
                step="1h",
            )
        except Exception as e:
            return {"error": str(e)}

    async def _get_availability(self, service: str, lookback_days: int) -> dict:
        try:
            return await self._prometheus.query_range(
                f'1 - (sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[5m])) / sum(rate(http_requests_total{{service="{service}"}}[5m])))',
                lookback_hours=lookback_days * 24,
                step="1h",
            )
        except Exception as e:
            return {"error": str(e)}

    async def _get_request_volume(self, service: str, lookback_days: int) -> dict:
        try:
            return await self._prometheus.query_range(
                f'sum(rate(http_requests_total{{service="{service}"}}[5m]))',
                lookback_hours=lookback_days * 24,
                step="1h",
            )
        except Exception as e:
            return {"error": str(e)}
