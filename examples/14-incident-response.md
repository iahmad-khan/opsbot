# Incident Response Playbook

End-to-end example of using OpsBot to investigate, contain, and fix a production incident.

---

## Scenario: Checkout service 5xx spike

A Prometheus alert fires: `checkout-service error rate > 5% for 10 minutes`.

---

## Phase 1 — Initial Triage (READ, instant)

```
@opsbot list pods in namespace checkout
```

→ OpsBot shows pod table. Three pods have high restart counts.

```
@opsbot show logs for checkout-api in namespace checkout last 100 lines
```

→ Logs show `OOMKilled` entries.

```
@opsbot get events in namespace checkout
```

→ K8s events confirm OOM evictions started at 14:32 UTC.

```
@opsbot what version is checkout-api deployed at?
```

→ `checkout-api:v2.3.1` deployed 25 minutes ago.

---

## Phase 2 — Deep Investigation (SRE Intelligence)

```
@opsbot investigate the checkout-service OOM issue over the last 30 minutes
```

→ OpsBot runs the RCA engine:
- Queries Prometheus: memory usage climbed 300% after v2.3.1 deploy
- Fetches pod logs: unclosed DB connection pool leaking
- Checks deployment history: v2.3.0 was stable for 5 days
- **Conclusion**: v2.3.1 introduced a DB connection pool leak

---

## Phase 3 — Containment (DESTRUCTIVE → approval required)

```
@opsbot scale checkout-api to 6 replicas in namespace checkout
```

→ WRITE: executes immediately, posts notification. Buys time while rollback is prepared.

```
@opsbot rollback deployment checkout-api in namespace checkout
```

→ DESTRUCTIVE: Slack sends approval button to SRE channel.

```
✅ @alice approved this operation — deploying checkout-api:v2.3.0...
```

→ Celery task executes `k8s_rollback_deployment`. Confirmation posted in thread.

```
@opsbot get pods in namespace checkout
```

→ All pods running v2.3.0, restart count reset to 0.

---

## Phase 4 — Alert Acknowledgement

```
@opsbot acknowledge the checkout-service alert in PagerDuty
```

→ WRITE: PagerDuty incident acknowledged.

```
@opsbot silence the checkout-memory alert for 2 hours in Prometheus
```

→ WRITE: Alertmanager silence created.

```
@opsbot annotate the grafana dashboard with "rollback to v2.3.0 at 14:55 UTC"
```

→ WRITE: Grafana annotation posted to checkout-service dashboard.

---

## Phase 5 — Root Cause & Fix PR

```
@opsbot analyze checkout-service and generate a fix PR for the DB connection leak
```

→ OpsBot:
1. Identifies the leaking code file from RCA evidence
2. Generates a fix patch closing the connection pool properly
3. Creates branch `opsbot-fix-1719676200` in `checkout-service` repo
4. Opens a draft PR: "fix: close DB connection pool in checkout handler"

```
📎 Fix PR created: https://github.com/my-org/checkout-service/pull/847
```

---

## Phase 6 — Post-Incident

```
@opsbot analyze SLOs for checkout-service
```

→ SLO analysis shows 30-minute error budget burn. Proposes updating SLO window.

```
@opsbot create an issue in checkout-service: "Post-incident: v2.3.1 DB connection leak" label incident
```

→ GitHub issue created, linked to PR.

---

## Key Timings

| Phase | Time | Action |
|---|---|---|
| 14:32 | Alert fires | — |
| 14:35 | Triage | READ ops, no approval |
| 14:40 | Scale up | WRITE, immediate |
| 14:42 | Rollback requested | Approval button sent |
| 14:43 | Rollback approved | 1 minute to approve |
| 14:44 | Rollback complete | Old version running |
| 14:47 | Alert silenced | — |
| 14:52 | Fix PR created | — |

Total time from alert to rollback: ~12 minutes. Manual process was 40–60 minutes.

---

## Caveats

- **Approval latency depends on approver availability.** During an incident, on-call should have Slack notifications enabled and respond quickly to approval buttons.
- **OpsBot cannot page people.** For initial alerting, use PagerDuty/OpsGenie. OpsBot *responds to* incidents, it doesn't create pages.
- **Fix PRs are a starting point**, not a final answer. The connection pool fix patch may need testing and refinement before merging. Never merge an OpsBot fix PR without engineer review.
- **Conversation context is per-thread.** Keep all incident commands in the same Slack thread to give OpsBot full context for subsequent questions.
