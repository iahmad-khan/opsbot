# Quick Start — OpsBot in 15 Minutes

Get OpsBot running locally, connected to your Kubernetes cluster(s) and Slack.

---

## Prerequisites

- Docker and Docker Compose v2
- A Slack workspace where you have admin rights
- `~/.kube/config` pointing at one or more clusters
- An Anthropic API key
- A running KAGENT installation (see step 2)

---

## Step 1 — Create `.env`

```bash
cp .env.example .env
```

Minimum required values:

```env
ANTHROPIC_API_KEY=sk-ant-...

SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

SECRET_KEY=change-me-in-production

# KAGENT controller endpoint (port-forwarded for local dev — see step 2)
KAGENT_URL=http://localhost:8083
KAGENT_NAMESPACE=opsbot
```

---

## Step 2 — Install KAGENT

OpsBot delegates all tool execution to KAGENT. Install it into your cluster:

```bash
helm upgrade -i kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent-system \
  --create-namespace \
  --set providers.anthropic.apiKeySecretRef=kagent-anthropic \
  --set providers.anthropic.model=claude-sonnet-4-6

# Create the LLM secret
kubectl create secret generic kagent-anthropic \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  -n kagent-system

# For local dev, port-forward the A2A endpoint
kubectl port-forward svc/kagent-controller 8083:8083 -n kagent-system &
```

---

## Step 3 — Start the OpsBot relay

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml exec backend alembic upgrade head
```

This starts: PostgreSQL · Redis · OpsBot FastAPI relay.

Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
# → {"status":"ok","db":"ok","redis":"ok"}
```

---

## Step 4 — Install OpsBot Helm chart (KAGENT CRDs)

The Helm chart creates the Agent/MCPServer/RemoteMCPServer CRDs that KAGENT needs to know about OpsBot:

```bash
# Create the kubeconfig secret (gives KAGENT tool server access to your clusters)
kubectl create secret generic opsbot-kubeconfig \
  --from-file=config=$HOME/.kube/config \
  -n opsbot --create-namespace

# Create app secrets
kubectl create secret generic opsbot-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=SLACK_BOT_TOKEN=xoxb-... \
  --from-literal=SLACK_APP_TOKEN=xapp-... \
  --from-literal=SLACK_SIGNING_SECRET=... \
  -n opsbot

# Install
helm dependency update charts/opsbot/
helm upgrade --install opsbot charts/opsbot/ \
  --namespace opsbot \
  -f charts/opsbot/values.yaml
```

---

## Step 5 — Invite the bot to Slack

1. Open a Slack channel (or create `#ops`)
2. Type `/invite @OpsBot`
3. Send a first message:

```
@opsbot which clusters are configured?
```

OpsBot calls `get_cluster_configuration`, reads the kubeconfig, and lists every context — no static list to maintain.

---

## Step 6 — Try common commands

```
@opsbot list pods in namespace default
@opsbot show logs for payment-service
@opsbot what is the current p99 latency for checkout-service?
@opsbot deploy v2.1.0 to staging cluster
@opsbot analyze payment-service and propose SLOs
```

---

## What runs where

| Component | Where |
|---|---|
| OpsBot relay (FastAPI) | Docker Compose (local) or K8s pod |
| KAGENT controller | `kagent-system` namespace |
| KAGENT tool server | `opsbot` namespace (kagent-tools pod) |
| GitHub/Datadog/Jira MCP pods | `opsbot` namespace |
| PostgreSQL | Docker Compose (local) or external |
| Redis | Docker Compose (local) or external |
| KAGENT UI | `http://localhost:8080` (via `kubectl port-forward`) |

KAGENT UI gives you a live view of agent executions, tool calls, and approval queues:

```bash
kubectl port-forward svc/kagent-ui 8080:80 -n kagent-system
```
