# OpsBot

An AI-powered DevOps and SRE automation platform built on [KAGENT](https://kagent.ai) — the Kubernetes-native AI agent framework. OpsBot lives in Slack; engineers ask in plain English, OpsBot acts. Destructive operations pause for a human approval click before anything runs.

---

## What it does

| Request | What happens |
|---|---|
| "deploy tag v1.2.3 to UAT" | Approval button posted → on click, `kubectl set image` or Helm upgrade |
| "check logs of payment-service" | `kubectl_logs` across all matching pods, errors summarised |
| "add @john to backend-api repo with push access" | GitHub MCP tool call, confirmation posted |
| "promote the canary rollout for checkout-api" | Argo Rollouts `promote_rollout` |
| "what is the current p99 latency for payment-service?" | PromQL `prometheus_query`, answer in Slack |
| "deploy tag v2.1.0 to prod cluster" | Agent discovers prod cluster context, approval required |
| "check logs across all clusters" | `get_cluster_configuration` → iterates every kubeconfig context |
| "analyze checkout-service and propose SLOs" | 30-day Prometheus query → SLO YAML → offers GitHub PR |
| "investigate the 5xx spike in payment-service" | Logs + metrics + K8s events → structured RCA report |
| "create a jira ticket for the payment timeout" | Jira MCP tool, confirmation in thread |

---

## Architecture

```
Slack DM / @opsbot mention
        │
        ▼
┌──────────────────────────────┐
│  OpsBot Relay (FastAPI)      │   Thin Slack Bolt gateway.
│  Socket Mode + slash cmds    │   Routes SLO/RCA requests directly to
│  asyncio background tasks    │   Python SRE modules; everything else
└────────────┬─────────────────┘   goes to KAGENT via A2A.
             │ HTTP POST (A2A / JSON-RPC)
             ▼
┌──────────────────────────────────────────────────────┐
│  KAGENT Controller  (port 8083)                      │
│  Kubernetes-native AI agent framework (Solo.io)      │
│  • Agent CRDs       — opsbot-general / slo / rca     │
│  • ModelConfig CRD  — Claude claude-sonnet-4-6            │
│  • Approval CRDs    — HITL gate (Pending → Approved) │
│  • Execution CRDs   — one per agent run              │
└──────────────────────┬───────────────────────────────┘
                       │ MCP / SSE
                       ▼
┌──────────────────────────────────────────────────────┐
│  KAGENT Tool Server  (port 8084)                     │
│  ghcr.io/kagent-dev/kagent/tools                     │
│  80+ tools in one pod — auto-discovered at runtime   │
│  ─────────────────────────────────────────────────── │
│  kubectl_get  kubectl_logs  kubectl_scale  rollout   │
│  helm_list  helm_upgrade  helm_install               │
│  promote_rollout  pause_rollout  set_rollout_image   │
│  prometheus_query  prometheus_range_query            │
│  grafana_dashboard_management  grafana_alert_*       │
│  cilium_status  istio_analyze  shell  …              │
│                                                      │
│  Kubeconfig with ALL clusters mounted as a Secret → │
│  agent discovers contexts via get_cluster_configuration │
└──────────────────────┬───────────────────────────────┘
                       │ MCPServer pods for tools not in kagent-tools
          ┌────────────┼───────────────┐
          ▼            ▼               ▼
   github-mcp     datadog-mcp      jira-mcp
   (official)     (custom)         (custom)
```

**Approval flow**

```
KAGENT pauses agent → creates Approval CRD (Pending)
        │
        ▼
OpsBot Approval Watcher (asyncio) reads CRD annotations
        │
        ▼
Posts Slack block-kit Approve / Deny buttons
        │
        ▼ (user clicks)
PATCH Approval CRD → status: Approved
        │
        ▼
KAGENT resumes agent execution
        │
        ▼
Result streamed back to Slack thread
```

---

## Repository layout

```
opsbot/
├── backend/
│   └── src/opsbot/
│       ├── kagent/           # A2A client, approval watcher, execution engine
│       ├── agent/            # Intent router (SLO/RCA/general), Redis memory
│       ├── api/              # FastAPI routes (/slack, /approvals, /sre, /health)
│       ├── integrations/     # Slack Bolt client + message formatters
│       ├── models/           # SQLAlchemy ORM (Task, Approval, AuditLog, User)
│       ├── sre/              # SLO analyzer, RCA engine, fix PR generator
│       ├── tools/            # Tool risk registry (READ / WRITE / DESTRUCTIVE)
│       └── workflows/        # Approval state machine, freeze windows
├── mcp-servers/
│   ├── datadog-mcp/          # Custom MCP server (no KAGENT official image yet)
│   └── jira-mcp/             # Custom MCP server (no KAGENT official image yet)
├── charts/opsbot/            # Helm chart
│   └── templates/kagent/
│       ├── model-config.yaml # ModelConfig CRD — Claude claude-sonnet-4-6
│       ├── agents.yaml       # Agent CRDs — opsbot-general / slo / rca
│       └── mcp-servers.yaml  # RemoteMCPServer + MCPServer CRDs
└── examples/                 # Step-by-step how-tos
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 + FastAPI + uvicorn |
| Agent framework | [KAGENT](https://kagent.ai) (CNCF sandbox, Solo.io) |
| LLM | Claude claude-sonnet-4-6 via KAGENT ModelConfig |
| Tool protocol | MCP over HTTP/SSE (KAGENT tool server) |
| ChatOps | Slack Bolt — Socket Mode |
| SRE intelligence | Python SLO analyzer + RCA engine + Fix PR generator |
| Database | PostgreSQL + SQLAlchemy (async) + Alembic |
| Cache / memory | Redis (conversation context prefetch) |
| Deployment | Kubernetes + Helm (KAGENT subchart) |
| UI | [KAGENT UI](https://github.com/kagent-dev/kagent) at `/ui` |

---

## Kubernetes cluster auto-discovery

OpsBot does **not** require a static list of cluster names. The KAGENT tool server is given a kubeconfig that contains all cluster contexts. At runtime:

1. The agent calls `get_cluster_configuration` — the tool reads the mounted kubeconfig and returns every context name.
2. The agent maps natural language ("prod cluster", "EU staging") to the nearest context name.
3. Every subsequent kubectl tool call receives `--context <name>`.

```
@opsbot list pods across all clusters
@opsbot deploy v2.1.0 to the production cluster
@opsbot check events in the eu-staging cluster
@opsbot which clusters are currently configured?
```

**Set it up once:**

```bash
# Merge all your kubeconfigs into one file, then create the secret
KUBECONFIG=~/.kube/prod:~/.kube/staging:~/.kube/dev \
  kubectl config view --flatten > /tmp/merged-kubeconfig

kubectl create secret generic opsbot-kubeconfig \
  --from-file=config=/tmp/merged-kubeconfig \
  -n opsbot
```

The secret is referenced in `values.yaml` under `kagent-tools.extraVolumes`. No Helm values change is needed when you add or remove clusters — recreate the secret and restart the tool server pod.

---

## Approval flow

Every tool call is classified before execution:

| Risk level | Examples | Behaviour |
|---|---|---|
| `READ` | List pods, get logs, query metrics, list rollouts | Auto-execute, no notification |
| `WRITE` | Scale replicas, add GitHub user, trigger pipeline, promote rollout | Execute + post notification |
| `DESTRUCTIVE` | Deploy tag, delete namespace, helm upgrade on prod, terraform apply | **Hold** — post Approve / Deny buttons; expires after 30 min |

Dual approval is configurable for the highest-risk operations (e.g. `kubectl_delete` on a namespace).

---

## Quick start (local dev)

### 1. Prerequisites

- Docker + Docker Compose v2
- A Slack workspace where you have admin rights
- `~/.kube/config` pointing at one or more clusters
- An Anthropic API key

### 2. Configure

```bash
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_SIGNING_SECRET
```

### 3. Start the stack

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml exec backend alembic upgrade head
```

This starts: PostgreSQL · Redis · OpsBot backend

### 4. Point to an existing KAGENT installation

OpsBot's relay connects to KAGENT via `KAGENT_URL` (default: `http://kagent-controller.kagent-system:8083`). For local dev, port-forward the KAGENT controller:

```bash
kubectl port-forward svc/kagent-controller 8083:8083 -n kagent-system
```

Or override in `.env`:

```env
KAGENT_URL=http://localhost:8083
KAGENT_NAMESPACE=opsbot
```

### 5. Verify

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
# → {"status":"ok","db":"ok","redis":"ok"}
```

### 6. Talk to OpsBot

```
@opsbot list pods in namespace default
@opsbot show logs for payment-service
@opsbot which clusters are configured?
@opsbot analyze checkout-service and propose SLOs
@opsbot investigate the 5xx spike in payment-service
```

---

## Configuration reference

All settings are environment variables (see [.env.example](.env.example)).

### Core

```env
ANTHROPIC_API_KEY=sk-ant-...
KAGENT_URL=http://kagent-controller.kagent-system:8083
KAGENT_NAMESPACE=opsbot

SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

DATABASE_URL=postgresql+asyncpg://opsbot:pass@localhost:5432/opsbot
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=change-me-in-production
```

### Tool-specific secrets (passed to KAGENT tool server)

| Integration | Required |
|---|---|
| Kubernetes | `opsbot-kubeconfig` Secret (see above) |
| GitHub | `GITHUB_TOKEN` (in `opsbot-secrets` K8s Secret) |
| Prometheus | `PROMETHEUS_URL` (in `kagent-tools.tools.prometheus.url`) |
| Grafana | `GRAFANA_API_KEY` (in `kagent-tools.tools.grafana.apiKey`) |
| Datadog | `DATADOG_API_KEY`, `DATADOG_APP_KEY` |
| Jira | `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN` |

### RBAC

Four roles mapped to Slack user IDs:

| Role | Capabilities |
|---|---|
| `admin` | All operations, approve all DESTRUCTIVE |
| `sre` | DESTRUCTIVE + WRITE, can approve |
| `developer` | READ + WRITE only |
| `readonly` | READ only |

```
/opsbot rbac add @username sre
/opsbot rbac list
```

---

## Deployment (Kubernetes)

See [examples/12-helm-production.md](examples/12-helm-production.md) for the full guide.

```bash
# 1. Create secrets
kubectl create secret generic opsbot-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=SLACK_BOT_TOKEN=xoxb-... \
  --from-literal=SLACK_APP_TOKEN=xapp-... \
  --from-literal=SLACK_SIGNING_SECRET=... \
  -n opsbot --create-namespace

# 2. Create merged kubeconfig secret (all clusters)
kubectl create secret generic opsbot-kubeconfig \
  --from-file=config=/tmp/merged-kubeconfig \
  -n opsbot

# 3. Install
helm dependency update charts/opsbot/
helm upgrade --install opsbot charts/opsbot/ \
  --namespace opsbot \
  --set image.repository=ghcr.io/your-org/opsbot-backend \
  --set image.tag=0.2.0 \
  -f charts/opsbot/values.yaml
```

---

## Verify KAGENT resources

```bash
# Agents
kubectl get agents -n opsbot
# NAME              READY   MODEL
# opsbot-general    True    claude-sonnet
# opsbot-slo        True    claude-sonnet
# opsbot-rca        True    claude-sonnet

# Tool server
kubectl get remotemcpservers -n opsbot
# NAME                          URL
# opsbot-kagent-tools           http://opsbot-kagent-tools.opsbot:8084/mcp

# Custom MCP pods
kubectl get mcpservers -n opsbot
# NAME           READY
# github-mcp     1/1
# datadog-mcp    1/1
# jira-mcp       1/1

# Approval queue
kubectl get approvals -n opsbot
```

---

## SRE intelligence

### SLO analysis

```
@opsbot analyze checkout-service and propose SLOs
```

Queries 30 days of Prometheus data → feeds to Claude → returns:
- Proposed SLO targets with current performance
- Error budget calculations
- Ready-to-apply `PrometheusRule` YAML
- Optionally opens a GitHub PR

### Root cause analysis

```
@opsbot investigate the 5xx spike in payment-service
```

Correlates pod logs + Prometheus metrics + K8s warning events → structured report:
- One-sentence root cause
- Evidence, timeline, contributing factors
- Remediation steps

---

## Slack commands

```
/opsbot help           Show available commands
/opsbot status         Show KAGENT URL, namespace, and agent status
/opsbot rbac list      List user roles
/opsbot rbac add @user <role>   Assign a role (admin only)
```

---

## Development

```bash
cd backend
pip install uv && uv pip install --system -e ".[dev]"

ruff check src/        # lint
mypy src/opsbot/       # types
pytest tests/ -v       # tests
```

---

## License

MIT
