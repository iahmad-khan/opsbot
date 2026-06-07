# Kubernetes Operations

OpsBot can read cluster state, tail logs, scale workloads, roll out new images, and roll back — all from Slack.

---

## Configuration

```env
# Path to kubeconfig — mounted into the container
KUBECONFIG_PATH=~/.kube/config

# Default namespace for commands that don't specify one
K8S_DEFAULT_NAMESPACE=default

# Multi-cluster (optional) — see "Multi-Cluster" section below
K8S_CONTEXTS=production,staging
```

In docker-compose, your `~/.kube/config` is bind-mounted into the backend and worker containers:

```yaml
volumes:
  - ~/.kube:/root/.kube:ro
```

---

## READ Operations (auto-execute, no approval)

```
@opsbot list pods in namespace payments
@opsbot show logs for checkout-api in namespace default
@opsbot get logs for pod checkout-api-7d9f5b-xkq2z last 200 lines
@opsbot describe deployment api-gateway in production namespace
@opsbot list all deployments in namespace default
@opsbot list events in namespace checkout
@opsbot get HPA for checkout-api
@opsbot what nodes are in the cluster
@opsbot describe node ip-10-0-1-42
@opsbot list services in namespace default
@opsbot show ingresses in production
```

---

## WRITE Operations (execute + post notification)

```
@opsbot restart deployment checkout-api in namespace default
@opsbot scale deployment api-gateway to 5 replicas in namespace production
@opsbot cordon node ip-10-0-1-42
@opsbot uncordon node ip-10-0-1-42
```

WRITE operations run immediately and post a notification in the thread. No button needed.

---

## DESTRUCTIVE Operations (require approval)

```
@opsbot deploy checkout-api:v2.1.0 to namespace production
@opsbot rollback deployment checkout-api in production
@opsbot rollback deployment api-gateway in production to revision 3
@opsbot delete pod checkout-api-7d9f5b-xkq2z in namespace default
@opsbot drain node ip-10-0-1-42
@opsbot delete namespace old-testing
```

For each DESTRUCTIVE operation, OpsBot posts a Slack message with **Approve / Deny** buttons. Any user with the `admin` or `sre` role can approve. The approver **cannot be the same person who requested the operation** (self-approval is blocked).

---

## Multi-Cluster Support

Set `K8S_CONTEXTS` to a comma-separated list of kubeconfig context names. OpsBot spawns one Kubernetes MCP server per context, and tools are namespaced per cluster:

```env
K8S_CONTEXTS=production,staging
```

Then in Slack:

```
@opsbot list pods in namespace default     # OpsBot asks which cluster
@opsbot show logs for checkout in production cluster
@opsbot deploy checkout:v2.1 to staging
```

The LLM will route to the correct cluster based on context clues in your message (environment name, explicit cluster mention).

> **Caveat:** Each context must exist in the kubeconfig file mounted at `KUBECONFIG_PATH`. Context names are case-sensitive and must match exactly.

---

## Caveats

- **Single cluster by default.** Without `K8S_CONTEXTS`, OpsBot uses whatever the active kubeconfig context is. To switch the active cluster, change the context in `~/.kube/config` and restart the containers.
- **Log truncation.** Pod logs are truncated to fit Slack's 3000-character block limit. Use `last 50 lines` to reduce output.
- **Rollback requires revision history.** Kubernetes rollback works by selecting a previous ReplicaSet. If `revisionHistoryLimit: 0` is set on the Deployment, rollback is unavailable.
- **Drain evicts ALL pods.** `kubectl drain` uses `--ignore-daemonsets`. Pods without disruption budgets will be evicted immediately. Use with caution in production.
- **Delete namespace is dual-approval.** `delete_namespace` is in the `REQUIRE_DUAL_APPROVAL_FOR` list by default. Two distinct admins/SREs must approve before it executes.
- **kubeconfig bind-mount is read-only.** The `:ro` flag prevents the container from modifying your local kubeconfig, but also means the bot cannot create kubeconfig entries. Set up all contexts locally before starting the stack.
