# ArgoCD Operations

OpsBot integrates with ArgoCD via a custom MCP server to sync apps, check health, view history, and roll back.

---

## Configuration

```env
ARGOCD_SERVER_URL=https://argocd.your-domain.com
ARGOCD_TOKEN=<argocd-api-token>
ARGOCD_INSECURE=false           # Set true for self-signed certs
```

### Generating an ArgoCD API token

```bash
argocd account generate-token --account opsbot
```

Or in the ArgoCD UI: **Settings → Accounts → opsbot → Generate Token**.

The `opsbot` account needs these permissions in your ArgoCD RBAC policy:

```csv
p, role:opsbot, applications, get, */*, allow
p, role:opsbot, applications, sync, */*, allow
p, role:opsbot, applications, update, */*, allow
p, role:opsbot, applications, delete, */*, deny
g, opsbot, role:opsbot
```

---

## READ Operations (auto-execute)

```
@opsbot list all ArgoCD apps
@opsbot get status of checkout-service in ArgoCD
@opsbot show sync history for payments-app
@opsbot what version is checkout deployed at?
@opsbot check ArgoCD health for all apps
```

---

## WRITE Operations (execute + notify)

```
@opsbot refresh checkout-service in ArgoCD
```

---

## DESTRUCTIVE Operations (require approval)

```
@opsbot sync checkout-service in ArgoCD
@opsbot sync payments-app and prune stale resources
@opsbot rollback checkout-app to previous version in ArgoCD
@opsbot rollback payments-app to revision 5 in ArgoCD
@opsbot delete ArgoCD app old-testing
```

---

## Building the ArgoCD MCP Server

The custom ArgoCD MCP server must be built before deployment:

```bash
cd mcp-servers/argocd-mcp
npm install
npm run build
```

The compiled output goes to `dist/index.js`. In the Helm chart and docker-compose, the backend image must include `mcp-servers/` — the default Dockerfile handles this.

---

## Caveats

- **Sync does NOT wait for completion.** `argocd_sync` triggers the sync and returns immediately. Use `argocd_get_app` to check if the sync completed successfully.
- **Rollback targets.** ArgoCD rollback uses history IDs, not image tags. Ask "show history for X" first to identify the revision ID you want.
- **`ARGOCD_INSECURE=true` is required** for ArgoCD servers using self-signed TLS certificates. Without it, MCP server connections will fail.
- **App names vs. labels.** ArgoCD apps are identified by their ArgoCD application name, not the Kubernetes deployment name. If your app is named `checkout-v2` in ArgoCD but `checkout-api` in K8s, use the ArgoCD name.
- **Multi-cluster ArgoCD.** ArgoCD manages multiple K8s clusters, but OpsBot addresses apps by ArgoCD application name. The destination cluster is transparent — you don't need separate configs per cluster for ArgoCD operations.
- **`sync_app` vs `argocd_sync`.** The MCP server exposes `sync_app`; the tools registry maps both names. Either works in natural language.
