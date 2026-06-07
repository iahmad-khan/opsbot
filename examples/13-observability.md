# Observability & Monitoring

OpsBot exposes Prometheus metrics, structured JSON logs, and a built-in audit trail.

---

## Metrics Endpoint

```bash
curl http://localhost:8000/metrics
```

Exposes Prometheus metrics via `prometheus_client`. Add a `ServiceMonitor` (included in the Helm chart) to scrape it automatically.

> **Caveat — `/metrics` is unauthenticated.** Ensure Prometheus can reach it on your internal network, but do not expose port 8000 directly to the internet.

---

## Key Metrics to Monitor

| Metric | Alert when |
|---|---|
| `http_requests_total{status=~"5.."}` | Error rate > 1% |
| `celery_task_failure_total` | Any non-zero spike |
| `celery_task_runtime_seconds` | p99 > 120s (agent timeout) |
| `redis_connected_clients` | Approaches `maxclients` limit |
| `pg_pool_size` / `pg_pool_checked_out` | Checked out ≈ pool size (connection exhaustion) |

---

## Grafana Dashboard

The Helm chart includes a `grafana-dashboard.yaml` ConfigMap. In a cluster with the Grafana operator, this is auto-loaded. Key panels:

- Task throughput (completed/failed per minute)
- Approval queue depth
- Agent loop iteration count
- MCP tool call latency per server
- Token budget consumed per user

---

## Structured Logging

OpsBot uses `structlog` for JSON logs. In development, logs are colorized human-readable. In production (`APP_ENV=production`), logs are JSON:

```json
{"event": "agent.tool_call", "tool": "kubernetes__list_pods", "risk": "READ", "iteration": 1, "request_id": "abc123", "user": "U012AB3CD"}
```

Configure your log aggregator (Loki, CloudWatch Logs, Datadog) to ingest from container stdout.

**Useful log queries (Loki LogQL):**

```logql
# All DESTRUCTIVE tool calls
{app="opsbot"} | json | risk = "DESTRUCTIVE"

# Approval decisions
{app="opsbot"} | json | event =~ "approval\\.approved|approval\\.denied"

# Errors by user
{app="opsbot"} | json | level = "error" | user != ""
```

---

## Token Budget

Per-user daily token consumption is stored in Redis and shown in Slack:

```
@opsbot how many tokens have I used today?
```

Key pattern: `opsbot:tokens:{slack_user_id}:{YYYY-MM-DD}`

Resets daily (25-hour TTL to cover timezone skew). To reset manually:

```bash
redis-cli -u redis://localhost:6379 DEL "opsbot:tokens:U012AB3CD:2026-06-07"
```

Configure the limit:

```env
LITELLM_DAILY_TOKEN_LIMIT=50000    # 0 = unlimited
```

---

## Audit Log Retention

All tool executions and approval decisions are written to the `audit_logs` PostgreSQL table. Rows are purged nightly at 02:00 UTC by the Celery beat task `purge_old_audit_logs_task`.

```env
AUDIT_LOG_RETENTION_DAYS=90    # default
```

To query the audit log directly:

```sql
SELECT actor_slack_id, action, tool_name, risk_level, success, created_at
FROM audit_logs
WHERE created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
LIMIT 100;
```

---

## Health Checks

| Endpoint | Description |
|---|---|
| `GET /alive` | Liveness probe — always returns 200 if process is alive |
| `GET /ready` | Readiness probe — checks Redis + PostgreSQL connectivity |
| `GET /health` | Detailed status of all subsystems including MCP servers |

Use `/ready` for Kubernetes readiness probes and `/alive` for liveness probes.

---

## Celery Monitoring (Flower)

Flower provides a web UI for Celery task monitoring:

```bash
# docker-compose
open http://localhost:5555

# Kubernetes port-forward
kubectl port-forward svc/opsbot-flower 5555:5555 -n opsbot
```

Flower shows queued tasks, active tasks, worker status, and task history.

---

## Caveats

- **Prometheus scrape interval.** Default scrape interval is 15s. For high-throughput alerting (e.g., task failure spike), reduce to 5s on the OpsBot scrape job.
- **Conversation memory is not logged.** Redis conversation history (`opsbot:conv2:*` keys) is ephemeral. Audit logs record tool calls but not the full chat history.
- **Rate limit events are logged at WARNING level** with `event: slack.rate_limited`. Alert on these to detect users who are hitting the limit unexpectedly.
