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
| "check timeout errors in elasticsearch logs for payment-service" | Queries OpenSearch/ES, returns top error patterns + timeline |
| "create a jira ticket for the payment-service timeout — high priority" | Creates Jira issue in the configured project |
| "what are the open PRs in the backend repo on bitbucket?" | Lists open PRs with author, branch, and CI status |
| "merge the hotfix MR in gitlab" | Merges GitLab MR (approval required) |
| "create a confluence page documenting this RCA in the SRE space" | Creates a formatted page in Confluence |
| "transition PROJ-123 to In Review and assign it to john" | Updates Jira issue status and assignee |
| "trigger the gitlab pipeline for backend on main" | Triggers CI/CD pipeline (write-gated) |
| "how many 5xx errors in the last 30 minutes in checkout?" | Counts matching log events with per-5min breakdown |
| "analyze log patterns for order-service and find the most frequent errors" | Aggregation of top error messages by frequency |

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
| OpenSearch / Elasticsearch | `OPENSEARCH_URL`, `OPENSEARCH_USERNAME` + `OPENSEARCH_PASSWORD` **or** `OPENSEARCH_API_KEY`, `OPENSEARCH_DEFAULT_INDEX` |
| Bitbucket Cloud | `BITBUCKET_WORKSPACE`, `BITBUCKET_USERNAME`, `BITBUCKET_APP_PASSWORD` |
| Bitbucket Server | `BITBUCKET_URL=https://bb.co`, `BITBUCKET_TOKEN` (PAT) |
| GitLab Cloud / Self-hosted | `GITLAB_URL`, `GITLAB_TOKEN` (api scope), `GITLAB_DEFAULT_GROUP` |
| Jira Cloud | `JIRA_URL=https://site.atlassian.net`, `JIRA_USERNAME` (email), `JIRA_API_TOKEN` |
| Jira Server / DC | `JIRA_URL=https://jira.co`, `JIRA_USERNAME`, `JIRA_API_TOKEN` (password or PAT) |
| Confluence Cloud | `CONFLUENCE_URL=https://site.atlassian.net/wiki`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` |
| Confluence Server / DC | `CONFLUENCE_URL=https://confluence.co`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` |

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

## Bitbucket, GitLab, Jira & Confluence

OpsBot integrates with the full Atlassian + GitLab ecosystem. Both Cloud and self-hosted Server/Data Center variants are supported — just point the URL to your instance.

### Example requests

```
# Bitbucket
@opsbot list open PRs in the backend repo
@opsbot create a PR from feature/payment-fix to main in backend repo
@opsbot merge PR #42 in payment-service repo
@opsbot trigger the staging pipeline on the hotfix branch in backend
@opsbot give john read access to the frontend repo

# GitLab
@opsbot show me open merge requests in group/backend project
@opsbot create a MR from feature/logging to main in backend/api
@opsbot what's the status of pipeline #1234 in backend/api?
@opsbot trigger a pipeline on the release branch for backend/api
@opsbot retry the failed pipeline #1234
@opsbot create an issue in backend/api: "Fix connection pool timeout"
@opsbot close issue #56 in backend/api

# Jira
@opsbot create a high-priority bug ticket: "payment-service timeout causing 5xx errors in prod"
@opsbot show me all open tickets in the SRE project
@opsbot what tickets are assigned to me?
@opsbot transition PROJ-123 to "In Review"
@opsbot assign PROJ-456 to alice
@opsbot add a comment to PROJ-789: "Deployed hotfix v1.2.1, monitoring for 30 min"
@opsbot link PROJ-123 to PROJ-100 as "blocks"
@opsbot search for issues with label "production-incident" in the last 7 days

# Confluence
@opsbot create a confluence page in SRE space titled "Incident RCA - Payment Service 2026-06-06"
@opsbot find the runbook for deploying the checkout service
@opsbot append the postmortem timeline to page ID 12345
@opsbot list pages in the SRE space
@opsbot create a page under the Incidents section documenting this outage
```

### Risk classification

| Operation | Risk level |
|---|---|
| Read PRs/MRs, issues, pages, pipelines | READ (auto-execute) |
| Create PR/MR, create issue, create page, add comment, update issue, transition issue, create branch, trigger pipeline | WRITE (execute + notify) |
| Merge PR/MR | DESTRUCTIVE (Slack approval required) |

### Atlassian Cloud vs Server/DC

For Atlassian Cloud, both Jira and Confluence share the same credentials:

```env
JIRA_URL=https://yoursite.atlassian.net
JIRA_USERNAME=you@company.com
JIRA_API_TOKEN=your-api-token          # from id.atlassian.com → Security → API tokens

CONFLUENCE_URL=https://yoursite.atlassian.net/wiki
CONFLUENCE_USERNAME=you@company.com    # same email
CONFLUENCE_API_TOKEN=your-api-token    # same token
```

For Server/DC, use username + password or a Personal Access Token (PAT):

```env
JIRA_URL=https://jira.yourcompany.com
JIRA_USERNAME=svc-opsbot
JIRA_API_TOKEN=your-pat-or-password

CONFLUENCE_URL=https://confluence.yourcompany.com
CONFLUENCE_USERNAME=svc-opsbot
CONFLUENCE_API_TOKEN=your-pat-or-password
```

### Bitbucket Cloud vs Server

```env
# Cloud — use an App Password (not your account password)
BITBUCKET_URL=https://api.bitbucket.org/2.0
BITBUCKET_WORKSPACE=your-workspace
BITBUCKET_USERNAME=your-username
BITBUCKET_APP_PASSWORD=your-app-password

# Server — use a Personal Access Token
BITBUCKET_URL=https://bitbucket.yourcompany.com
BITBUCKET_TOKEN=your-pat
```

### GitLab

```env
GITLAB_URL=https://gitlab.com            # or https://gitlab.yourcompany.com
GITLAB_TOKEN=your-personal-access-token  # requires: api, read_user scopes
GITLAB_DEFAULT_GROUP=your-group          # default for project listing
```

---

## OpenSearch / Elasticsearch log analysis

OpsBot connects to your existing OpenSearch or Elasticsearch cluster (both use the same REST API — no code changes needed between the two).

### Example queries

```
@opsbot check timeout errors in elasticsearch logs for payment-service
@opsbot show me error logs from checkout-service in the last 2 hours
@opsbot how many 5xx errors in the last 30 minutes in order-service?
@opsbot analyze log patterns for payment-service and find the most frequent errors
@opsbot find slow queries in the order-service logs
@opsbot what services are generating the most errors right now?
```

### Available tools

| Tool | Description |
|---|---|
| `search_logs` | Full-text search with service, level, and time filters |
| `get_error_summary` | Top error messages by frequency + error timeline |
| `count_events` | Count matching log events with per-5-min breakdown |
| `search_slow_queries` | Find timeout/slow patterns across common frameworks |
| `get_log_field_values` | Top values for any field (status codes, services, etc.) |
| `list_indices` | Discover available index patterns in the cluster |

### Configuration

```env
OPENSEARCH_URL=http://opensearch.internal:9200

# Basic auth
OPENSEARCH_USERNAME=opsbot
OPENSEARCH_PASSWORD=secret

# OR API key (Elastic Cloud / OpenSearch Serverless)
OPENSEARCH_API_KEY=base64encodedkey==

# Index pattern — adjust to match how you ship logs
# filebeat:   OPENSEARCH_DEFAULT_INDEX=filebeat-*
# fluentd:    OPENSEARCH_DEFAULT_INDEX=fluentd-*
# Logstash:   OPENSEARCH_DEFAULT_INDEX=logstash-*
# ECS/OTel:   OPENSEARCH_DEFAULT_INDEX=logs-*
OPENSEARCH_DEFAULT_INDEX=logs-*
```

### Local development with OpenSearch

```bash
# Start OpenSearch alongside the rest of the stack
docker compose -f docker/docker-compose.yml --profile opensearch up -d
```

This spins up a single-node OpenSearch 2.17 on `:9200` with security disabled (dev only).

### Field compatibility

The integration auto-detects log fields across the most common shipping formats:

| Field purpose | Checked fields |
|---|---|
| Service name | `service.name`, `kubernetes.labels.app`, `app`, `fields.service` |
| Log level | `log.level`, `level`, `severity`, `loglevel` |
| Timestamp | `@timestamp` (ECS standard) |
| Message | `message`, `msg`, `log.message` |

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
| `opensearch-mcp` | `search_logs`, `get_error_summary`, `count_events`, `search_slow_queries`, `get_log_field_values`, `list_indices` |
| `bitbucket-mcp` | `list_repos`, `list_prs`, `get_pr`, `create_pr`, `merge_pr`, `decline_pr`, `add_pr_comment`, `list_branches`, `create_branch`, `get_pipeline_status`, `trigger_pipeline`, `add_user_to_repo` |
| `gitlab-mcp` | `list_projects`, `get_project`, `list_mrs`, `get_mr`, `create_mr`, `merge_mr`, `list_issues`, `get_issue`, `create_issue`, `update_issue`, `add_issue_comment`, `list_pipelines`, `get_pipeline`, `trigger_pipeline`, `retry_pipeline`, `cancel_pipeline`, `list_branches`, `create_branch`, `add_member`, `list_tags`, `create_tag` |
| `jira-mcp` | `search_issues`, `get_issue`, `create_issue`, `update_issue`, `add_comment`, `transition_issue`, `assign_issue`, `list_projects`, `list_transitions`, `get_my_issues`, `search_users`, `link_issues`, `get_issue_changelog` |
| `confluence-mcp` | `search_pages`, `get_page`, `create_page`, `update_page`, `append_to_page`, `add_comment`, `list_spaces`, `get_space`, `get_page_children`, `move_page` |

Build them:

```bash
for srv in argocd-mcp prometheus-mcp datadog-mcp opensearch-mcp bitbucket-mcp gitlab-mcp jira-mcp confluence-mcp; do
  (cd mcp-servers/$srv && npm install && npm run build)
done
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
