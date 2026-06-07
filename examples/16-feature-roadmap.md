# Feature Roadmap & Product Engineering Analysis

An honest assessment of OpsBot's current state, implemented gaps, and suggested next features.

---

## Implemented (as of current build)

### Core Capabilities
- Multi-LLM agent loop (Claude, OpenAI, Gemini, Bedrock, Ollama)
- 8 custom MCP servers + external K8s and GitHub servers (148+ tools total)
- 3-tier approval workflow: READ → auto, WRITE → notify, DESTRUCTIVE → approval button
- Role-based access control (admin, sre, developer, readonly)
- Per-Slack-channel conversation memory (24h Redis TTL)
- Token budget per user per day
- Dual approval for dangerous operations
- Per-tool 30-second timeout
- Rate limiting (10 req/min per user)
- Audit log with 90-day retention
- SRE intelligence: SLO analysis, RCA engine, automated fix PRs
- 8 Slack formatters (pod tables, deployment tables, SLO proposals, RCA reports)
- Next.js dashboard (approvals, tasks, SLOs, audit log)
- Helm chart with HPA, pre-upgrade migration job, redbeat scheduler
- Prometheus metrics + Grafana dashboard ConfigMap
- Structured JSON logging with request correlation IDs

### Gaps fixed in this session
| Gap | Fix |
|---|---|
| Agent silent for 30–120s during tool chains | Progress callback updates "⏳ Working on it..." message per tool |
| Self-approval not blocked | `approve()` rejects if `approver_slack_id == requester_slack_id` |
| Dashboard has no auth | NextAuth credentials provider + backend `/api/auth/token` endpoint + middleware |
| Single-cluster Kubernetes only | `K8S_CONTEXTS` spawns one MCP server per context |
| No GitHub Actions triggering | `trigger_workflow()` method + `create_workflow_dispatch` in tools registry |
| No deployment freeze windows | `FREEZE_DEPLOYMENT_DAYS/START/END_UTC` checked in agent + approval workflow |

---

## Suggested Future Features (P1)

### 1. Slack OAuth for Dashboard Auth
Currently the dashboard uses a shared password (`DASHBOARD_SECRET`). Replacing this with Slack OAuth would give per-user identity in the dashboard, matching who approved what in Slack. NextAuth already supports the Slack OAuth provider.

```env
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
```

### 2. Streaming LLM Responses to Slack
The agent posts a final answer only after the full LLM response arrives. For long chains, users see per-tool progress but not partial text. Streaming LLM output and updating the Slack message in chunks would significantly improve UX for verbose responses.

### 3. Incident Auto-Detection
Subscribe to Prometheus Alertmanager webhook → auto-trigger RCA when a P1 alert fires. No human message needed.

```
POST /webhooks/alertmanager → trigger RCA task → post to #incidents
```

### 4. Multi-Cluster Context Awareness
With `K8S_CONTEXTS` set, the LLM can target specific clusters. But when the user doesn't specify a cluster, the bot should ask or use a sensible default rather than guessing. Add a `k8s_default_context` setting.

### 5. Approval Self-Service via Slash Command
Allow an approver to approve from a slash command without clicking a button:
```
/opsbot approve <approval-id>
/opsbot deny <approval-id> reason: too risky on Friday
```

### 6. Automated SLO Reporting
Weekly digest to `#sre-reports` for every configured service. Already possible via Celery beat; needs dashboard UI to configure which services + which channel.

### 7. Deployment Freeze Calendar UI
The freeze window is currently environment-variable-configured. A dashboard page to set freeze windows with a date picker would be more user-friendly for managing release freezes.

---

## Suggested Future Features (P2)

### 8. Secret Scanning in Approval Messages
Scan `tool_args` before posting the approval Slack message. If any value looks like an API key or password (regex match), redact it from the displayed args.

### 9. Terraform Plan Diffs in Slack
Currently Terraform plan output is truncated to fit Slack blocks. For large plans, post the full diff as a file attachment or Slack file upload.

### 10. GitHub Actions Status Feed
Subscribe to GitHub Actions webhook events → post build status to relevant Slack threads.

### 11. On-Call Aware Approvals
When a DESTRUCTIVE operation is requested outside business hours, automatically page the on-call engineer via PagerDuty instead of (or in addition to) sending a Slack button.

### 12. RBAC Namespace Scoping
Currently `sre` role allows WRITE operations in all namespaces. Add namespace-scoped roles:
```sql
-- sre_payments can only operate in the payments namespace
```

### 13. Webhook Receiver for External Events
A `/webhooks/` endpoint family for:
- Alertmanager
- GitHub push/PR events
- ArgoCD sync notifications
- Custom tool callbacks

### 14. Policy as Code
Allow teams to define policies (e.g., "never deploy to production on Friday after 5pm") in YAML, stored in Git, evaluated by the approval engine.

---

## Known Limitations

| Limitation | Severity | Notes |
|---|---|---|
| SRE modules hardcode `claude-sonnet-4-6` model | Medium | Should read `LITELLM_DEFAULT_MODEL` |
| SLO analyzer hardcodes `channel_id=req.requester_slack_id` | Low | Should use actual channel |
| Azure/GCP cloud tools are shallow stubs | Low | Only list/describe; no create/delete |
| No streaming LLM output | Medium | Fixed by progress callback, but not true streaming |
| Dashboard approver input is manual (type Slack ID) | Low | Should use Slack OAuth for identity |
| MCP servers don't auto-restart on crash | Medium | Restart backend pod to recover |
| Fix PR branches accumulate in GitHub | Low | Add periodic stale-branch cleanup |
