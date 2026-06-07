# MCP Servers

OpsBot connects to external tools via the Model Context Protocol (MCP). It uses 8 custom TypeScript MCP servers plus external ones for Kubernetes and GitHub.

---

## Architecture

```
Agent Engine
    │
    └── MCP Manager (mcp/manager.py)
            │
            ├── kubernetes-mcp-server  (npx)
            ├── @modelcontextprotocol/server-github  (npx)
            ├── terraform-mcp-server  (docker)
            ├── argocd-mcp  (custom: mcp-servers/argocd-mcp)
            ├── prometheus-mcp  (custom: mcp-servers/prometheus-mcp)
            ├── datadog-mcp  (custom: mcp-servers/datadog-mcp)
            ├── opensearch-mcp  (custom: mcp-servers/opensearch-mcp)
            ├── bitbucket-mcp  (custom: mcp-servers/bitbucket-mcp)
            ├── gitlab-mcp  (custom: mcp-servers/gitlab-mcp)
            ├── jira-mcp  (custom: mcp-servers/jira-mcp)
            └── confluence-mcp  (custom: mcp-servers/confluence-mcp)
```

MCP servers run as **child processes** (stdio transport). Each server exposes a list of tools; the MCP Manager discovers them at startup and makes them available to the LLM.

---

## Building Custom MCP Servers

All custom servers are TypeScript and must be compiled before the backend can launch them:

```bash
for srv in argocd-mcp prometheus-mcp datadog-mcp opensearch-mcp bitbucket-mcp gitlab-mcp jira-mcp confluence-mcp; do
    cd mcp-servers/$srv
    npm install
    npm run build
    cd ../..
done
```

The compiled `dist/index.js` file is what the backend runs. The Dockerfile copies the entire `mcp-servers/` tree into the image.

---

## Configuring Which Servers Start

Each server only starts if its required configuration is present. The guard conditions in `mcp/servers.py`:

| Server | Starts when |
|---|---|
| `kubernetes` | `MCP_KUBERNETES_COMMAND` is set (always) |
| `github` | `GITHUB_TOKEN` is non-empty |
| `terraform` | `TFE_TOKEN` is set OR `TERRAFORM_WORKING_DIR` exists |
| `argocd` | `ARGOCD_SERVER_URL` is non-empty |
| `prometheus` | `PROMETHEUS_URL` is non-empty |
| `datadog` | `DATADOG_API_KEY` is non-empty |
| `opensearch` | `OPENSEARCH_URL` is non-empty |
| `bitbucket` | `BITBUCKET_USERNAME` is non-empty |
| `gitlab` | `GITLAB_TOKEN` is non-empty |
| `jira` | `JIRA_URL` is non-empty |
| `confluence` | `CONFLUENCE_URL` is non-empty |

---

## Checking Server Status

In Slack:

```
/opsbot status
```

Or call the health endpoint:

```bash
curl http://localhost:8000/health | jq '.checks.mcp_servers'
```

---

## Tool Naming Convention

Tools from MCP servers are namespaced with a double-underscore prefix:

```
kubernetes__list_pods
github__list_repositories
argocd__sync_app
prometheus__query_range
```

The tools registry (`tools/registry.py`) maps both the prefixed name and the bare name to the same risk level, so both resolve correctly.

---

## Multi-cluster Kubernetes

When `K8S_CONTEXTS` is set, servers are named per context:

```
kubernetes-production__list_pods
kubernetes-staging__list_pods
```

The LLM routes to the correct server based on context clues in your message.

---

## Overriding MCP Server Commands

```env
# Use a locally built argocd-mcp instead of the default path
MCP_ARGOCD_COMMAND=node /custom/path/argocd-mcp/dist/index.js

# Use a specific version of the kubernetes server
MCP_KUBERNETES_COMMAND=npx -y kubernetes-mcp-server@1.2.3

# Use a local Terraform binary instead of Docker
MCP_TERRAFORM_COMMAND=npx -y @hashicorp/terraform-mcp-server
```

---

## Caveats

- **MCP servers run as child processes and are NOT automatically restarted.** If a server crashes after startup, its tools become unavailable. The health endpoint shows the degraded status but does not restart it. Restart the backend pod to reconnect.
- **Failed servers don't block startup.** If an MCP server fails to connect, a warning is logged and it is skipped. Other tools remain available.
- **Tool discovery happens at startup.** If a new tool is added to a running MCP server, it won't appear until the backend restarts.
- **PID leak on worker restart.** MCP server processes are started by the FastAPI process but Celery workers don't own them. On `docker-compose restart worker`, the MCP children from the backend process are unaffected. This is expected behavior.
- **Slow servers block startup.** The `initialize()` call uses `asyncio.gather()` — all servers connect concurrently, but startup won't complete until the slowest one succeeds or times out (30 seconds default).
- **`npx` servers download on first run.** If `kubernetes-mcp-server` or `@modelcontextprotocol/server-github` are not pre-cached, they'll be fetched from npm during startup. Use a specific version tag and pre-cache in the Dockerfile for production.
