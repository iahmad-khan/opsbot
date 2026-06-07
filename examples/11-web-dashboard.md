# Web Dashboard

The Next.js dashboard provides a visual management layer for approvals, task history, SLO health, and audit logs.

---

## Pages

| URL | Description |
|---|---|
| `/dashboard` | Active tasks, pending approval count, SLO health cards |
| `/approvals` | Pending approval queue — Approve / Deny with one click |
| `/tasks` | Full task history with status, requester, and log viewer |
| `/slos` | Per-service SLO burn rate charts and error budget gauges |
| `/audit` | Full audit log with filters by user, action, and date |

---

## Running Locally

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

The dev server proxies `/api/backend/*` to `http://localhost:8000`.

---

## Authentication Setup

Dashboard auth is **disabled by default** (local dev mode). To enable it:

```env
# In your .env file (or docker-compose environment)
DASHBOARD_SECRET=your-secure-password
SECRET_KEY=a-random-32-byte-hex-string    # Used as JWT signing key
NEXTAUTH_SECRET=${SECRET_KEY}
NEXTAUTH_URL=http://your-dashboard-domain.com
```

When `DASHBOARD_SECRET` is set:
1. Visiting any page redirects to `/login`.
2. The login form calls the backend at `POST /api/auth/token` with the password.
3. On success, a 24-hour JWT session is stored in a NextAuth session cookie.
4. Subsequent requests include the session cookie and pass through the middleware.

When `DASHBOARD_SECRET` is **not** set, all pages are accessible without login (suitable for networks with perimeter security).

> **Generate a secure random key:**
> ```bash
> python -c "import secrets; print(secrets.token_hex(32))"
> ```

---

## Environment Variables

| Variable | Required when auth enabled | Description |
|---|---|---|
| `DASHBOARD_SECRET` | Yes | Password users enter on the login page |
| `SECRET_KEY` | Yes | JWT signing key (must match backend `SECRET_KEY`) |
| `NEXTAUTH_SECRET` | Yes | NextAuth JWT encryption key (can be same as `SECRET_KEY`) |
| `NEXTAUTH_URL` | Yes (prod) | Full public URL of the dashboard (e.g. `https://opsbot.company.com`) |
| `API_URL` | Yes | Internal URL the Next.js server uses to call the backend (e.g. `http://backend:8000`) |
| `NEXT_PUBLIC_API_URL` | Optional | Public API URL for client-side calls |

---

## Approving from the Dashboard

1. Go to `/approvals`.
2. Find the pending request.
3. Enter your Slack User ID in the approver field (format: `U012AB3CD`).
4. Click **Approve** or **Deny**.

> **Caveat:** The dashboard doesn't look up your Slack identity automatically — you must enter your Slack User ID. This is a known UX gap. A future improvement would integrate Slack OAuth so users authenticate with their Slack account.

> **Caveat:** Self-approval is enforced at the backend. Even if you enter your own Slack User ID as approver for a request you created, the backend will reject it with "You cannot approve your own request."

---

## Real-time Updates

The dashboard uses **SWR** (stale-while-revalidate) to poll for updates. Polling intervals:
- Pending approvals: every 5 seconds
- Task status: every 10 seconds
- SLO data: every 30 seconds

There is **no WebSocket** connection — updates arrive on the next poll cycle, not in real-time. For immediate feedback, use Slack.

---

## Caveats

- **Dashboard auth uses a shared password**, not per-user accounts. Everyone with the `DASHBOARD_SECRET` has full dashboard access. Future improvement: integrate Slack OAuth for per-user identity.
- **`NEXTAUTH_URL` must match the actual public URL** in production. If it doesn't match, session cookies won't be set correctly and login will fail.
- **Port 3000 should not be internet-exposed** unless HTTPS is in front of it. Put the dashboard behind your ingress/load balancer with TLS termination.
- **The backend API itself is not protected by the dashboard auth.** The backend has its own JWT auth for programmatic access, but the dashboard's NextAuth session is separate. Don't confuse the two.
