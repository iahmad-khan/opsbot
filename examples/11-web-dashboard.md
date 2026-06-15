# KAGENT UI

OpsBot uses the KAGENT UI as its web dashboard. It is deployed as part of the KAGENT controller installation and provides live visibility into agent executions, tool calls, approval queues, and model configuration.

No custom frontend is required.

---

## Accessing the UI

### Local dev (port-forward)

```bash
kubectl port-forward svc/kagent-ui 8080:80 -n kagent-system
```

Open `http://localhost:8080`.

### Production (Ingress)

The KAGENT Helm chart supports exposing the UI via Ingress. Add to your KAGENT values:

```yaml
# kagent-values.yaml (passed when installing the kagent subchart)
ui:
  ingress:
    enabled: true
    className: nginx
    hosts:
      - host: opsbot-ui.internal.company.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: opsbot-ui-tls
        hosts:
          - opsbot-ui.internal.company.com
```

---

## What the KAGENT UI shows

| View | Description |
|---|---|
| **Agents** | All registered Agent CRDs (`opsbot-general`, `opsbot-slo`, `opsbot-rca`), status, last execution |
| **Executions** | Live and historical agent runs with full tool call trace |
| **Approvals** | Pending Approval CRDs — approve or deny directly from the UI |
| **Tool Servers** | Status of `RemoteMCPServer` and `MCPServer` resources, registered tools |
| **Model Config** | Active `ModelConfig` CRDs (LLM provider, model, API key reference) |

---

## Approval management

Approval CRDs created by KAGENT (when a DESTRUCTIVE tool is requested) appear in both:
1. **Slack** — as interactive Approve / Deny buttons (via OpsBot's approval watcher)
2. **KAGENT UI** — as entries in the Approvals view

Approving from either surface patches `status.phase: Approved` on the CRD, which resumes the agent.

---

## Audit trail

KAGENT exposes Prometheus metrics on every agent pod at `/metrics`. OpsBot also writes a PostgreSQL `audit_log` table for every completed tool call. Both sources are queryable:

```bash
# KAGENT metrics (per agent)
kubectl port-forward svc/opsbot-kagent-tools 8084:8084 -n opsbot
curl http://localhost:8084/metrics | grep kagent_tools_mcp_invocations_total

# OpsBot audit log (via API)
curl http://localhost:8000/api/v1/audit?limit=50
```

---

## Observability

Enable OpenTelemetry tracing in the tool server:

```yaml
kagent-tools:
  otel:
    tracing:
      enabled: true
      exporter:
        otlp:
          endpoint: "http://tempo.monitoring.svc.cluster.local:4317"
          insecure: true
```

Enable ServiceMonitor for Prometheus scraping:

```yaml
kagent-tools:
  tools:
    metrics:
      servicemonitor:
        enabled: true
        interval: 30s
        labels:
          release: prometheus
```
