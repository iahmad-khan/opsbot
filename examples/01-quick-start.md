# Quick Start — OpsBot in 15 Minutes

Get OpsBot running locally with Docker Compose, connected to your Kubernetes cluster and Slack.

---

## Prerequisites

- Docker and Docker Compose v2
- A Slack workspace where you have admin rights
- `kubectl` configured with a `~/.kube/config` pointing at a cluster
- An Anthropic API key (or any LiteLLM-compatible provider)

---

## Step 1 — Create a `.env` file

Copy `.env.example` to `.env` at the repo root and fill in the required values:

```bash
cp .env.example .env
```

Minimum required values:

```env
# LLM (at least one provider)
ANTHROPIC_API_KEY=sk-ant-...

# Slack (see 02-slack-setup.md)
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
SLACK_SIGNING_SECRET=...

# Security (generate a real key for anything beyond local dev)
SECRET_KEY=change-me-in-production
```

---

## Step 2 — Start the stack

```bash
cd docker
docker compose up -d
```

This starts: PostgreSQL, Redis, the FastAPI backend, the Celery worker, the Celery beat scheduler, and the Next.js frontend.

Confirm all services are healthy:

```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Expected response from `/ready`:

```json
{"status": "ok", "db": "ok", "redis": "ok"}
```

---

## Step 3 — Run database migrations

Migrations run automatically via Docker Compose's backend startup, but if you need to run them manually:

```bash
docker compose exec backend alembic upgrade head
```

---

## Step 4 — Invite the bot to Slack

1. In Slack, open a channel (or create `#ops-bot`)
2. Type `/invite @OpsBot`
3. Send a message:

```
@OpsBot list pods in namespace default
```

The bot should respond with a table of pods within a few seconds.

---

## Step 5 — Try an approval flow

```
@OpsBot restart deployment nginx in namespace default
```

For WRITE operations you'll see a Slack notification. For DESTRUCTIVE operations a Slack message with **Approve / Deny** buttons is sent to the approvers. See [07 — Approvals & RBAC](07-approvals-and-rbac.md) for setup.

---

## Step 6 — Open the web dashboard

Navigate to [http://localhost:3000](http://localhost:3000). The dashboard shows:

- Active tasks and their status
- Pending approval queue
- SLO health cards

> **Caveat — dashboard has no authentication in the current build.** The backend API is protected by JWT, but the Next.js frontend does not enforce a login screen. Do not expose port 3000 on a network where untrusted users can reach it. See [11 — Web Dashboard](11-web-dashboard.md) for hardening steps.

---

## Stopping the stack

```bash
cd docker
docker compose down
# To also remove persistent data:
docker compose down -v
```

---

## Key caveats

- **`~/.kube/config` is bind-mounted** into the backend and worker containers at `/root/.kube/config`. Ensure the current context points at the cluster you want the bot to operate on.
- **Single-cluster only.** Context switching between multiple clusters is not yet implemented. To target a different cluster, change the active `kubectl` context and restart the containers.
- **Conversation memory resets after 24 hours.** Redis TTL is 86400 seconds (configurable via `CONVERSATION_CONTEXT_TTL`). The bot will not remember messages from the previous day.
- **Socket mode requires the Slack app to be online.** If the backend crashes, the Slack connection is lost and the bot stops responding. The `restart: unless-stopped` policy in docker-compose handles most cases.
