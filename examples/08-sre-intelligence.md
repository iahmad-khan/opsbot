# SRE Intelligence — SLO Analysis, RCA, Fix PRs

OpsBot's SRE module goes beyond reactive commands: it analyzes service health, performs root cause analysis, and generates automated fix pull requests.

---

## SLO Analysis

Analyzes 30 days of Prometheus metrics and proposes SLIs/SLOs for a service.

```
@opsbot analyze SLOs for checkout-service
@opsbot propose SLOs for payments-api in namespace default
@opsbot analyze checkout-service and create a GitHub PR with the SLO rules
```

### What it does

1. Queries Prometheus for error rate, p50/p99 latency, and availability over the lookback window.
2. Calculates a recommended error rate SLO, latency SLO, and availability SLO.
3. Generates a PrometheusRule YAML with recording rules.
4. Optionally creates a GitHub PR adding the YAML to `monitoring/slos/{service}.yaml`.

### Configuration

```env
PROMETHEUS_URL=http://prometheus.monitoring.svc:9090
GITHUB_TOKEN=ghp_...         # Required for PR creation
GITHUB_ORG=my-org
```

> **Caveat — Model is currently hardcoded** in `sre/slo_analyzer.py` to `claude-sonnet-4-6`. It does not follow `LITELLM_DEFAULT_MODEL`. This is a known gap.

---

## Root Cause Analysis (RCA)

Multi-signal correlation across Prometheus, pod logs, K8s events, and Datadog.

```
@opsbot investigate the 5xx spike in checkout-service over the last 2 hours
@opsbot what caused the latency increase in payments-api between 14:00 and 15:30 UTC
@opsbot run RCA on the checkout-service incident
@opsbot why are checkout pods crashing?
```

### What it collects

- Prometheus metrics (error rate, request rate, latency, saturation)
- Kubernetes events for the service namespace
- Recent pod logs (last 500 lines per pod)
- Deployment history (image tags, rollout times)
- Datadog traces (if configured)

### Output format

The RCA report includes:
- **Summary**: one-paragraph description of the incident
- **Evidence**: timestamped signals that led to the conclusion
- **Root cause**: identified cause (code change, OOM, downstream dependency, etc.)
- **Recommended actions**: rollback, scale up, fix code, etc.

> **Caveat — Evidence collection can take 30–60 seconds** for complex incidents. During this time, OpsBot's Slack message shows per-tool progress ("🔧 Running `prometheus__query_range`...").

---

## Automated Fix PRs

After an RCA, OpsBot can generate a code fix and submit it as a pull request.

```
@opsbot generate a fix PR for the memory leak in checkout-api
@opsbot create a fix PR for the issue found in the RCA
```

### What it generates

1. Analyzes the affected files identified in the RCA.
2. Generates a patch (code change, config update, or Helm values change).
3. Creates a branch `opsbot-fix-{timestamp}` in the target repo.
4. Commits the fix with a description of the change.
5. Opens a draft PR with the full RCA summary in the PR body.

### Configuration

```env
GITHUB_TOKEN=ghp_...
GITHUB_ORG=my-org
```

> **Caveat — Fix PRs are draft PRs.** They are marked as draft to prevent accidental merge without human review. A human engineer must review the patch, run tests, and approve before merging.

> **Caveat — Fix quality varies** with incident complexity. For simple cases (wrong config, OOM limit too low), the fix is reliable. For logic bugs, treat it as a starting point, not a final solution.

---

## Scheduled SLO Reports

Configure weekly SLO health summaries sent to Slack automatically:

```python
# In celery_app.py beat_schedule, add:
"weekly-slo-report": {
    "task": "opsbot.tasks.celery_app.run_slo_analysis_task",
    "schedule": crontab(day_of_week="monday", hour=9, minute=0),
    "kwargs": {
        "service_name": "checkout-service",
        "namespace": "default",
        "lookback_days": 7,
        "requester_slack_id": "U_BOT",
        "channel_id": "#ops-team",
    },
},
```

---

## Caveats

- **Prometheus must be reachable.** SLO analysis and RCA both query Prometheus directly. If your Prometheus requires auth, configure the MCP server command to pass credentials.
- **SRE modules use a hardcoded model** (`claude-sonnet-4-6`). If you switch to a different LLM provider via `LITELLM_DEFAULT_MODEL`, the general agent switches but the SRE modules do not.
- **SLO YAML is a starting point.** The generated PrometheusRule YAML uses conservative defaults. Review thresholds against your actual SLAs and adjust before merging.
- **RCA requires meaningful log patterns.** If logs are unstructured or empty, the RCA engine falls back to metrics-only analysis, which may be less precise.
- **Fix PR branches accumulate.** Consider adding a cleanup step or naming convention to make stale fix branches easy to identify and delete.
