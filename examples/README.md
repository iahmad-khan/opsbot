# OpsBot Examples & How-To Guides

Practical guides for deploying and operating OpsBot on KAGENT.

---

## Getting started

| Guide | Description |
|---|---|
| [01 — Quick Start](01-quick-start.md) | Run OpsBot locally in 15 minutes |
| [02 — Slack Setup](02-slack-setup.md) | Create the Slack app, configure Socket Mode |
| [12 — Helm Production](12-helm-production.md) | Production Kubernetes deployment with KAGENT |

## Kubernetes & cluster operations

| Guide | Description |
|---|---|
| [03 — Kubernetes](03-kubernetes.md) | kubectl tools, multi-cluster auto-discovery, Helm, Argo Rollouts |

## Source control & CI/CD

| Guide | Description |
|---|---|
| [04 — GitHub](04-github.md) | PR management, branch operations, CI status |
| [05 — ArgoCD](05-argocd.md) | GitOps sync via shell tool or custom MCP server |
| [06 — Terraform](06-terraform.md) | Plan and apply via shell tool |

## Approvals & access control

| Guide | Description |
|---|---|
| [07 — Approvals & RBAC](07-approvals-and-rbac.md) | Approval flow, roles, freeze windows, dual approval |

## SRE intelligence

| Guide | Description |
|---|---|
| [08 — SRE Intelligence](08-sre-intelligence.md) | SLO analysis and root cause analysis |
| [13 — Observability](13-observability.md) | Prometheus metrics, Grafana, OTel tracing |
| [14 — Incident Response](14-incident-response.md) | PagerDuty, OpsGenie, RCA workflow |

## Integrations

| Guide | Description |
|---|---|
| [09 — Multi-LLM](09-multi-llm.md) | Switch between Claude, GPT-4, Gemini, Bedrock |
| [10 — MCP Servers](10-mcp-servers.md) | KAGENT tool server, custom MCP pods, adding integrations |
| [11 — KAGENT UI](11-web-dashboard.md) | Web dashboard, approval management, observability |
| [15 — Additional Integrations](15-additional-integrations.md) | Datadog, Jira, and other custom MCP servers |

---

## Architecture summary

```
Slack → OpsBot relay → KAGENT A2A → Agent pod → KAGENT tool server
                                                  (kubectl, helm, prometheus, grafana, ...)
                                                → GitHub MCPServer pod
                                                → Datadog MCPServer pod
                                                → Jira MCPServer pod
```

Cluster access is auto-discovered from the kubeconfig mounted into the tool server — no static context list.
