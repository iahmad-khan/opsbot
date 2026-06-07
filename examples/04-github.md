# GitHub Operations

OpsBot can manage repository members, list PRs, create PRs and issues, and trigger GitHub Actions workflows.

---

## Configuration

```env
GITHUB_TOKEN=ghp_...        # Personal Access Token or Fine-Grained PAT
GITHUB_ORG=my-org           # Default org for all repo operations
```

### Required PAT scopes

| Scope | Purpose |
|---|---|
| `repo` | Read/write repo content, PRs, issues |
| `read:org` | List org members |
| `write:org` | Add/remove org members |
| `admin:org` | Required for team management |
| `workflow` | Trigger GitHub Actions workflows |
| `read:user` | Get user info |

> **Caveat — Fine-Grained PATs.** If your org enforces Fine-Grained PATs, create one for the OpsBot service account scoped to the specific repositories it needs to operate on. Organization-level permissions (member management) may require a Classic PAT with `admin:org`.

---

## READ Operations (auto-execute, no approval)

```
@opsbot list repositories in my-org
@opsbot list collaborators on checkout-service
@opsbot show open PRs in payments-api
@opsbot get CI status for checkout-service branch main
@opsbot list issues in backend-api assigned to me
```

---

## WRITE Operations (execute + notify)

```
@opsbot add @john to repo checkout-service with push access
@opsbot remove @jane from repo legacy-api
@opsbot create PR in checkout-service: "fix: payment timeout" from branch hotfix/timeout to main
@opsbot create branch hotfix/v2-auth in backend-api from main
@opsbot create issue in payments-api: "Memory leak in checkout flow" label bug
```

---

## GitHub Actions Triggering (WRITE)

OpsBot can trigger `workflow_dispatch` workflows:

```
@opsbot trigger deploy.yml workflow in checkout-service on branch main
@opsbot run the integration-tests workflow in backend-api on branch release/v2
@opsbot trigger release.yml in payments-service on tag v1.2.3 with inputs: {"environment": "staging"}
```

**Risk level: WRITE** — the workflow run can be cancelled if triggered in error. It does NOT require an approval button.

> **Caveat:** The target workflow file must have `on: workflow_dispatch` configured. If the workflow doesn't have that trigger, the dispatch will fail silently.

---

## Caveats

- **`GITHUB_ORG` is required** for multi-repo operations. Without it, the bot tries to operate on your user account's repos.
- **The official GitHub MCP server** (`@modelcontextprotocol/server-github`) is used for most operations. It exposes different tool names than the custom `tools/github.py` file. The tools registry maps both.
- **Self-hosted GitHub Enterprise** requires setting the base URL via the MCP server env var (not directly supported via OpsBot settings yet). Edit `mcp/servers.py` to pass `GITHUB_HOST` to the MCP server env.
- **PR creation from fix generator** creates branches like `opsbot-fix-{timestamp}`. These accumulate — consider a periodic cleanup job.
- **Workflow inputs must be valid JSON.** If the LLM can't parse the inputs correctly, simplify your request.
