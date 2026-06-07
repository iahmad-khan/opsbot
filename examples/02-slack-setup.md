# Slack App Setup

Full step-by-step guide to create the Slack application that OpsBot uses.

---

## Step 1 — Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App → From scratch**.
2. Name it `OpsBot` and pick your workspace.

---

## Step 2 — Enable Socket Mode

Under **Settings → Socket Mode**:
- Toggle **Enable Socket Mode** to ON.
- Generate an **App-Level Token** with the `connections:write` scope. This is your `SLACK_APP_TOKEN` (`xapp-...`).

> **Caveat — Socket Mode requires the backend to stay connected.** If the FastAPI process crashes, Slack messages stop being processed. The `restart: unless-stopped` policy in docker-compose handles most crashes. In Kubernetes, a liveness probe at `/alive` restarts unhealthy pods.

---

## Step 3 — Configure OAuth & Permissions

Under **OAuth & Permissions → Bot Token Scopes**, add these scopes:

| Scope | Purpose |
|---|---|
| `app_mentions:read` | Receive `@OpsBot` mentions |
| `chat:write` | Post messages |
| `chat:write.public` | Post to channels the bot hasn't joined |
| `channels:history` | Read message history (for thread context) |
| `groups:history` | Same for private channels |
| `im:history` | Read DMs |
| `im:write` | Initiate DMs |
| `users:read` | Look up user info (display name, email) |
| `users:read.email` | Needed for RBAC lookup by email |
| `commands` | Slash command `/opsbot` |

Click **Install to Workspace** and copy the **Bot User OAuth Token** (`xoxb-...`). This is your `SLACK_BOT_TOKEN`.

---

## Step 4 — Enable Event Subscriptions

Under **Event Subscriptions**:
- Toggle **Enable Events** to ON.
- Under **Subscribe to bot events**, add:
  - `app_mention`
  - `message.im`

> **Caveat — No public URL needed.** OpsBot uses Socket Mode, so you do NOT need to set a Request URL. The Slack API pushes events over a persistent WebSocket.

---

## Step 5 — Register the Slash Command

Under **Slash Commands → Create New Command**:
- Command: `/opsbot`
- Request URL: `https://your-domain/slack/commands` (can be anything; with socket mode it's not used)
- Short description: `DevOps & SRE automation`

---

## Step 6 — Enable Interactivity

Under **Interactivity & Shortcuts**:
- Toggle **Interactivity** ON.
- Request URL: `https://your-domain/slack/actions` (placeholder; socket mode handles this)

This is required for the Approve/Deny buttons in approval messages to work.

---

## Step 7 — Copy credentials to `.env`

```env
SLACK_BOT_TOKEN=xoxb-...         # from OAuth & Permissions page
SLACK_APP_TOKEN=xapp-...         # from Socket Mode page (App-Level Token)
SLACK_SIGNING_SECRET=...         # from App Credentials (Basic Information)
SLACK_DEFAULT_CHANNEL=#ops-bot   # channel to use for default notifications
```

---

## Step 8 — Invite the bot to channels

The bot can only post to channels it has been invited to:

```
/invite @OpsBot
```

Invite it to at minimum:
- `#ops-bot` — default notification channel
- Any channel your team will mention it in

---

## Rate limits

OpsBot enforces a per-user rate limit of **10 requests per 60 seconds** (configurable by editing `_RATE_LIMIT_MAX` in `handlers.py`). Users who exceed this get a "slow down" message and their request is dropped. Adjust if your team is large.

---

## Caveats

- **Approval messages expose tool args.** The Slack approval Block Kit card shows the tool name and arguments. Avoid putting secret values (tokens, passwords) in tool invocations — use environment variables and config references instead.
- **Thread context.** Messages in the same Slack thread share conversation memory. Messages in different threads are independent sessions.
- **Bot mentions only.** In channels, the bot only responds to `@OpsBot` mentions, not every message. In DMs, it responds to every message.
- **Private channels require explicit invitation.** The bot must be invited to a private channel before it can post or respond there.
