RCA_ANALYSIS_PROMPT = """\
Perform a Root Cause Analysis for the following incident.

## Incident
{incident_description}

## Evidence Gathered
### Pod Logs
```
{pod_logs}
```

### Prometheus Metrics
```
{metrics}
```

### Kubernetes Events
```
{k8s_events}
```

### Recent Deployments
```
{recent_deployments}
```

### Additional Context
{additional_context}

## Instructions
Analyze all evidence and produce a structured RCA report.

Respond in this exact JSON format:
{{
  "root_cause": "One clear sentence describing the root cause",
  "confidence": 0.85,
  "summary": "2-3 sentence executive summary",
  "contributing_factors": [
    "Factor 1",
    "Factor 2"
  ],
  "evidence": {{
    "key_log_entries": ["relevant log line 1", "relevant log line 2"],
    "metric_anomalies": ["metric anomaly description"],
    "k8s_events": ["relevant event"],
    "deployment_correlation": "description of any deployment correlation"
  }},
  "timeline": [
    {{"time": "relative time", "event": "what happened"}},
  ],
  "remediation_steps": [
    "Immediate: Step 1",
    "Short-term: Step 2",
    "Long-term: Step 3"
  ],
  "recommended_actions": [
    {{"action": "description", "priority": "high|medium|low", "owner": "team"}}
  ]
}}
"""


SLO_ANALYSIS_PROMPT = """\
Analyze the following service metrics and propose appropriate SLOs.

## Service: {service_name}
## Analysis Period: {lookback_days} days

## Metrics Data
### Error Rate (requests per second, 5xx rate)
```
{error_rate_data}
```

### Latency Percentiles (ms)
```
{latency_data}
```

### Availability
```
{availability_data}
```

### Request Volume
```
{request_volume_data}
```

## Instructions
Based on the historical data, propose SLIs and SLOs following Google SRE best practices.

Respond in this exact JSON format:
{{
  "service_name": "{service_name}",
  "analysis_summary": "Brief description of service reliability characteristics",
  "proposed_slos": [
    {{
      "name": "availability",
      "sli_description": "The proportion of successful requests",
      "sli_metric": "sum(rate(http_requests_total{{status!~\"5..\",service=\"{service_name}\"}}[5m])) / sum(rate(http_requests_total{{service=\"{service_name}\"}}[5m]))",
      "target": 0.999,
      "current_performance": 0.9987,
      "window": "30d",
      "error_budget_minutes": 43.2
    }},
    {{
      "name": "latency",
      "sli_description": "The proportion of requests faster than 200ms",
      "sli_metric": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service=\"{service_name}\"}}[5m]))",
      "target": 0.95,
      "current_performance": 0.96,
      "window": "30d",
      "p99_ms": 185
    }}
  ],
  "slo_yaml": "Full Kubernetes PrometheusRule YAML for the SLOs",
  "recommendations": [
    "Specific actionable recommendation"
  ]
}}
"""
