# OpsBot Examples & How-To Guides

Practical configuration guides and example Slack commands for every OpsBot feature.

---

## Index

| Guide | Description |
|---|---|
| [01 — Quick Start](01-quick-start.md) | Get OpsBot running in 15 minutes using Docker Compose |
| [02 — Slack App Setup](02-slack-setup.md) | Create and configure the Slack app (scopes, socket mode, events) |
| [03 — Kubernetes Operations](03-kubernetes.md) | Pod inspection, log tailing, rollouts, rollbacks, scaling |
| [04 — GitHub Operations](04-github.md) | User management, repo listing, PR creation |
| [05 — ArgoCD](05-argocd.md) | App sync, rollback, health checks |
| [06 — Terraform](06-terraform.md) | Plan, apply, state inspection |
| [07 — Approvals & RBAC](07-approvals-and-rbac.md) | Approval workflow, role assignment, dual-approval |
| [08 — SRE Intelligence](08-sre-intelligence.md) | SLO analysis, RCA engine, automated fix PRs |
| [09 — Multi-LLM Configuration](09-multi-llm.md) | Switching between Claude, OpenAI, Gemini, Bedrock, Ollama |
| [10 — MCP Servers](10-mcp-servers.md) | Custom MCP server setup, building, and troubleshooting |
| [11 — Web Dashboard](11-web-dashboard.md) | Next.js dashboard: approvals, task history, SLO view |
| [12 — Production Helm Deployment](12-helm-production.md) | Helm chart values, secrets, HPA, ingress, migrations |
| [13 — Observability & Monitoring](13-observability.md) | Metrics, token budgets, audit log retention, Grafana |
| [14 — Incident Response Playbook](14-incident-response.md) | End-to-end incident workflow from alert to fix PR |
| [15 — Additional Integrations](15-additional-integrations.md) | Jira, Confluence, OpenSearch, Bitbucket, GitLab, PagerDuty, OpsGenie, Datadog |
| [16 — Feature Roadmap](16-feature-roadmap.md) | Product gaps, missing features, and suggested improvements |

---

## Quick Reference: Slack Commands

```
# Read operations — execute instantly, no approval
@opsbot list pods in namespace payments
@opsbot show logs for checkout-api
@opsbot describe deployment api-gateway in production
@opsbot get ArgoCD app status for checkout

# Write operations — execute + post notification
@opsbot restart deployment checkout-api
@opsbot scale deployment api-gateway to 5 replicas
@opsbot add user @jane to github repo payments-service

# Destructive operations — require approval button
@opsbot deploy checkout-api:v2.1.0 to production
@opsbot rollback deployment checkout-api to previous version
@opsbot run terraform apply in payments-infra
@opsbot delete namespace old-testing

# SRE intelligence
@opsbot analyze SLOs for checkout-service
@opsbot investigate the 5xx spike in payments over the last 2 hours
@opsbot generate a fix PR for the memory leak in checkout-api

# Slash commands
/opsbot help
/opsbot status
/opsbot rbac add @user sre
```

---

## Architecture at a Glance

```
Slack DM / Channel mention
        │
        ▼
Slack Bolt (socket mode)
        │
        ▼
FastAPI  ──►  Agent Engine (ReAct loop)
                 │         │
          LiteLLM (LLM)   MCP Manager
                 │              │
          Tool calls     MCP Servers (K8s, ArgoCD, Prometheus...)
                 │
          Approval needed?
          ├── No (READ)      → execute → respond
          ├── WRITE          → execute → notify Slack
          └── DESTRUCTIVE    → Slack button → Celery task → execute
```
