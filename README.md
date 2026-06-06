# OpsBot 🤖

An advanced AI-powered DevOps & SRE automation platform. Stop answering "can you deploy this?", "can you check the logs?", "can you add me to this repo?" — let OpsBot handle it.

OpsBot lives in Slack. Engineers ask naturally, OpsBot acts. Destructive operations require a human approval click before anything runs.

---

## What it does

| Request | How OpsBot handles it |
|---|---|
| "deploy tag v1.2.3 to UAT" | Posts an approval button → on click, patches the K8s deployment |
| "check logs of payment-service" | Fetches pod logs, summarizes errors |
| "add @john to backend-api repo with push access" | Calls GitHub API, posts confirmation |
| "sync checkout-app in ArgoCD" | Triggers ArgoCD sync (approval required) |
| "rollback payment-service to previous version" | Rollback via K8s/ArgoCD (approval required) |
| "run terraform plan in staging" | Runs plan, posts diff to Slack |
| "analyze checkout-service and propose SLOs" | Queries 30-day Prometheus data, generates SLO YAML, offers to open a PR |
| "investigate the 5xx spike in payment-service" | Correlates logs + metrics + K8s events, produces structured RCA |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           OPSBOT                                 │
├──────────────────────────┬──────────────────────────────────────┤
│  Slack (ChatOps)         │  Next.js Web Dashboard               │
│  • Socket Mode           │  • Approval Queue                    │
│  • Slash commands        │  • Task History                      │
│  • Interactive messages  │  • SLO Health / RCA Reports          │
│                          │  • Audit Log                         │
├──────────────────────────┴──────────────────────────────────────┤
│                     FastAPI Backend (async)                       │
│       /slack/events  /tasks  /approvals  /sre  /health           │
├─────────────────────────────────────────────────────────────────┤
│                       Agent Engine                               │
│   LiteLLM (Claude/GPT-4/Gemini/Bedrock/Ollama)                  │
│   ReAct loop · Redis conversation memory · Approval gates        │
├─────────────────────────────────────────────────────────────────┤
│                      MCP Tool Layer                              │
│  kubernetes · github · argocd · terraform · aws · gcp · azure   │
│  prometheus · grafana · pagerduty · opsgenie · datadog           │
├─────────────────────────────────────────────────────────────────┤
│                   SRE Intelligence                               │
│   SLO Analyzer · RCA Engine · Fix PR Generator                   │
├─────────────────────────────────────────────────────────────────┤
│                      Data Layer                                   │
│   PostgreSQL (tasks, approvals, audit, RBAC)                     │
│   Redis (sessions, conversation context, task queue)             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Repository layout

```
opsbot/
├── backend/                    # Python 3.12 + FastAPI service
│   ├── src/opsbot/
│   │   ├── agent/              # LiteLLM wrapper, ReAct loop, memory, prompts
│   │   ├── api/                # FastAPI routes
│   │   ├── config/             # Pydantic settings
│   │   ├── integrations/       # Slack Bolt, GitHub client
│   │   ├── mcp/                # MCP process manager + client
│   │   ├── models/             # SQLAlchemy ORM + Pydantic schemas
│   │   ├── sre/                # SLO analyzer, RCA engine, fix generator
│   │   ├── tasks/              # Celery async tasks
│   │   ├── tools/              # Tool implementations (K8s, GitHub, ArgoCD…)
│   │   └── workflows/          # Approval state machine + Slack notifications
│   ├── alembic/                # Database migrations
│   └── tests/
├── frontend/                   # Next.js 14 dark-mode dashboard
├── mcp-servers/                # Custom TypeScript MCP servers
│   ├── argocd-mcp/
│   ├── prometheus-mcp/
│   └── datadog-mcp/
├── charts/opsbot/              # Helm chart (HPA, ServiceMonitor, Ingress)
├── docker/docker-compose.yml   # Local dev stack
└── .github/workflows/          # CI (lint/test) + release (build/push/deploy)
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend language | Python 3.12 |
| API framework | FastAPI + uvicorn |
| LLM abstraction | LiteLLM (Claude · GPT-4o · Gemini · Bedrock · Ollama) |
| Agent loop | Custom ReAct (tool use / function calling) |
| MCP integration | Official `mcp` Python SDK (stdio client) |
| ChatOps | Slack Bolt for Python — Socket Mode |
| Task queue | Celery + Redis |
| Database | PostgreSQL + SQLAlchemy (async) + Alembic |
| Cache / sessions | Redis |
| Web dashboard | Next.js 14 (App Router) + Tailwind CSS |
| Deployment | Kubernetes + Helm |
| CI/CD | GitHub Actions |

---

## Approval flow

Every tool call is classified before execution:

| Risk level | Examples | Behavior |
|---|---|---|
| `READ` | List pods, get logs, query metrics | Auto-execute, no notification |
| `WRITE` | Restart deployment, add GitHub user, scale replicas | Execute + post notification to Slack |
| `DESTRUCTIVE` | Deploy tag, rollback, terraform apply, delete namespace | **Hold** — post Approve / Deny buttons in Slack; also approvable from the web dashboard |

Approvals expire after a configurable timeout (default 30 min). High-risk operations (e.g. `delete_namespace`) can require dual approval.

---

## Quick start (local dev)

### 1. Prerequisites

- Docker + Docker Compose
- A Slack app with:
  - **Bot Token Scopes**: `app_mentions:read`, `channels:history`, `chat:write`, `files:write`, `im:history`, `im:write`, `reactions:write`, `users:read`, `users:read.email`
  - **Event Subscriptions**: `app_mention`, `message.im`
  - **Interactive Components** enabled
  - **Socket Mode** enabled — grab the App-Level Token (`xapp-…`)
  - **Slash Commands**: `/opsbot`

### 2. Configure

```bash
cp .env.example .env
```

Fill in at minimum:

```env
ANTHROPIC_API_KEY=sk-ant-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...
```

### 3. Start the stack

```bash
docker compose -f docker/docker-compose.yml up -d
```

This starts: **PostgreSQL · Redis · Backend API · Celery worker · Celery beat · Next.js dashboard · Flower** (Celery monitor on `:5555`).

### 4. Run database migrations

```bash
docker compose -f docker/docker-compose.yml exec backend alembic upgrade head
```

### 5. Verify

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Open the dashboard: [http://localhost:3000](http://localhost:3000)

### 6. Talk to OpsBot in Slack

```
@opsbot list pods in namespace default
@opsbot check logs of my-service
@opsbot deploy tag v2.0.1 to staging
@opsbot analyze payment-service and propose SLOs
```

---

## Configuration reference

All settings are environment variables (see [.env.example](.env.example)).

### LLM providers

```env
# Default — Claude Sonnet via Anthropic
LITELLM_DEFAULT_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...

# Switch to OpenAI
LITELLM_DEFAULT_MODEL=gpt-4o
OPENAI_API_KEY=sk-...

# Switch to Gemini
LITELLM_DEFAULT_MODEL=gemini/gemini-1.5-pro
GOOGLE_API_KEY=...

# Local Ollama
LITELLM_DEFAULT_MODEL=ollama/llama3.2
OLLAMA_BASE_URL=http://localhost:11434
```

### Integrations to enable

| Integration | Required env vars |
|---|---|
| Kubernetes | `KUBECONFIG_PATH` (or in-cluster) |
| GitHub | `GITHUB_TOKEN`, `GITHUB_ORG` |
| ArgoCD | `ARGOCD_SERVER_URL`, `ARGOCD_TOKEN` |
| Terraform | `TERRAFORM_WORKING_DIR`, `TFE_TOKEN` (optional) |
| AWS | `AWS_REGION` + IAM role or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| GCP | `GOOGLE_APPLICATION_CREDENTIALS`, `GCP_PROJECT` |
| Azure | `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` |
| Prometheus | `PROMETHEUS_URL` |
| Grafana | `GRAFANA_URL`, `GRAFANA_TOKEN` |
| PagerDuty | `PAGERDUTY_API_KEY`, `PAGERDUTY_FROM_EMAIL` |
| OpsGenie | `OPSGENIE_API_KEY` |
| DataDog | `DATADOG_API_KEY`, `DATADOG_APP_KEY` |

### RBAC

OpsBot has four roles mapped to Slack user IDs:

| Role | Capabilities |
|---|---|
| `admin` | All operations, including all DESTRUCTIVE |
| `sre` | DESTRUCTIVE + WRITE (can approve their own requests) |
| `developer` | READ + WRITE (no rollbacks, no terraform apply) |
| `readonly` | READ only |

Configure via Slack: `/opsbot rbac add @username sre`

Set fallback approvers (for when no SRE is online):

```env
DEFAULT_APPROVER_SLACK_IDS=U012AB3CD,U056EF7GH
```

---

## SRE intelligence

### SLO analysis

```
@opsbot analyze checkout-service and propose SLOs
```

OpsBot queries 30 days of Prometheus data (error rate, p99 latency, availability), feeds it to Claude, and returns:
- Proposed SLO targets with current performance vs. target
- Error budget calculations
- Ready-to-apply `PrometheusRule` YAML
- Optionally opens a GitHub PR to add the rules

### Root cause analysis

```
@opsbot investigate the 5xx spike in payment-service over the last 2 hours
```

OpsBot:
1. Fetches pod logs (last 200 lines per pod)
2. Queries Prometheus for error rate + latency + memory metrics
3. Lists K8s Warning events
4. Lists recent deployments
5. Feeds everything to Claude with a structured RCA prompt
6. Returns: root cause, confidence %, timeline, contributing factors, remediation steps
7. Optionally creates a GitHub issue + fix PR

---

## Deployment (Kubernetes)

### Helm install

```bash
# Create the secrets first
kubectl create secret generic opsbot-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=SLACK_BOT_TOKEN=xoxb-... \
  --from-literal=SLACK_APP_TOKEN=xapp-... \
  --from-literal=SLACK_SIGNING_SECRET=... \
  --from-literal=DATABASE_URL=postgresql+asyncpg://... \
  --from-literal=REDIS_URL=redis://... \
  -n opsbot --create-namespace

# Install
helm install opsbot ./charts/opsbot \
  --namespace opsbot \
  --set image.repository=ghcr.io/your-org/opsbot-backend \
  --set image.tag=1.0.0 \
  -f charts/opsbot/values.yaml
```

### CI/CD

Push a tag to trigger a full build + deploy:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The [release workflow](.github/workflows/release.yml) will:
1. Build and push backend + frontend + MCP server Docker images to GHCR
2. Run `helm upgrade --install` against your cluster

---

## Custom MCP servers

Three custom MCP servers are included in `mcp-servers/`:

| Server | Tools |
|---|---|
| `argocd-mcp` | `list_apps`, `get_app`, `sync_app`, `rollback_app`, `get_app_history`, `refresh_app` |
| `prometheus-mcp` | `query_metrics`, `query_range`, `list_alerts`, `list_rules`, `list_targets`, `silence_alert` |
| `datadog-mcp` | `query_metrics`, `get_logs`, `list_monitors`, `get_monitor`, `mute_monitor` |

Build them:

```bash
cd mcp-servers/argocd-mcp && npm install && npm run build
cd mcp-servers/prometheus-mcp && npm install && npm run build
cd mcp-servers/datadog-mcp && npm install && npm run build
```

OpsBot also connects to these off-the-shelf MCP servers automatically when configured:
- [`kubernetes-mcp-server`](https://www.npmjs.com/package/kubernetes-mcp-server)
- [`@modelcontextprotocol/server-github`](https://www.npmjs.com/package/@modelcontextprotocol/server-github)
- [`terraform-mcp-server`](https://hub.docker.com/r/hashicorp/terraform-mcp-server)

---

## Development

### Backend

```bash
cd backend
pip install uv
uv pip install --system -e ".[dev]"

# Lint
ruff check src/
mypy src/opsbot/

# Tests
pytest tests/ -v
```

### Frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
npm run build
```

### MCP servers

```bash
cd mcp-servers/argocd-mcp
npm install
npm run dev
```

---

## Web dashboard

| Page | URL | Description |
|---|---|---|
| Dashboard | `/dashboard` | Overview: active tasks, pending approvals, MCP server status |
| Approvals | `/approvals` | Pending approval queue with Approve / Deny buttons |
| Tasks | `/tasks` | Full task history with filters by status / user / channel |
| SLO Health | `/slos` | SLO analysis reports and RCA reports |
| Audit Log | `/audit` | Every operation ever executed, searchable by actor or tool |

---

## Slack commands

```
/opsbot help       Show all available commands
/opsbot status     Check MCP server connection status
/opsbot rbac list  List user roles
/opsbot rbac add @user <role>   Assign a role (admin only)
```

---

## License

MIT
