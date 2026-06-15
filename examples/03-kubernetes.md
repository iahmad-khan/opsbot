# Kubernetes Operations

OpsBot uses the KAGENT tool server's built-in kubectl tools. All cluster contexts in the mounted kubeconfig are auto-discovered at runtime — no static list is needed.

---

## Cluster auto-discovery

The KAGENT tool server reads the kubeconfig mounted at `/root/.kube/config`. When an engineer asks about "the production cluster" or "staging", the agent:

1. Calls `get_cluster_configuration` — returns every context name from the kubeconfig.
2. Fuzzy-matches the natural language cluster name to a context.
3. Passes `--context <name>` to every subsequent kubectl tool call.

```
@opsbot which clusters are configured?
# → prod-us-east, prod-eu-west, staging, dev

@opsbot list pods across all clusters
@opsbot check events in the eu-west cluster
@opsbot show logs for checkout-api in production
@opsbot deploy v2.1.0 to staging cluster
```

---

## Setup

### Single cluster (in-cluster)

If OpsBot runs inside the target cluster, no secret is needed. The tool server uses the pod's ServiceAccount token automatically.

```yaml
# values.yaml
kagent-tools:
  extraVolumes: []   # no kubeconfig secret needed
```

### Multi-cluster

Create a merged kubeconfig containing all cluster contexts, then load it as a Secret:

```bash
# Merge all kubeconfigs
KUBECONFIG=~/.kube/prod:~/.kube/staging:~/.kube/dev \
  kubectl config view --flatten > /tmp/merged.yaml

# Create secret in opsbot namespace
kubectl create secret generic opsbot-kubeconfig \
  --from-file=config=/tmp/merged.yaml \
  -n opsbot
```

The secret name is configured in `values.yaml` (default: `opsbot-kubeconfig`):

```yaml
kagent-tools:
  extraVolumes:
    - name: kubeconfig
      secret:
        secretName: opsbot-kubeconfig
        optional: true
  extraVolumeMounts:
    - name: kubeconfig
      mountPath: /root/.kube
      readOnly: true
```

**Adding a cluster later:** merge it into the kubeconfig, recreate the secret, and restart the tool server pod:

```bash
kubectl rollout restart deployment/opsbot-kagent-tools -n opsbot
```

No Helm values changes needed.

---

## Token refresh for cloud providers

Cloud-managed clusters (EKS, GKE, AKE) normally use `exec`-based credential plugins (`aws eks get-token`, `gke-cloud-auth-plugin`). These do not work inside the KAGENT tool server pod because the cloud CLIs are not installed.

**Recommended approach: static ServiceAccount tokens**

Create a long-lived ServiceAccount token in each remote cluster and use it in the kubeconfig:

```bash
# In each remote cluster:
kubectl create serviceaccount opsbot -n kube-system
kubectl create clusterrolebinding opsbot \
  --clusterrole=cluster-admin \
  --serviceaccount=kube-system:opsbot

# Extract the token (Kubernetes 1.24+)
kubectl create token opsbot -n kube-system --duration=8760h > /tmp/prod-token

# Build a kubeconfig entry without exec:
kubectl config set-credentials opsbot-prod \
  --token=$(cat /tmp/prod-token)
kubectl config set-context prod \
  --cluster=prod \
  --user=opsbot-prod
```

Then merge the context into your master kubeconfig as shown above.

---

## Available kubectl tools

These tools are built into the KAGENT tool server — no extra pods needed:

| Tool | Description |
|---|---|
| `kubectl_get` | List or get resources (`pods`, `deployments`, `services`, …) |
| `kubectl_describe` | Full resource description |
| `kubectl_logs` | Fetch pod logs (supports `--previous`, `--since`) |
| `kubectl_scale` | Scale a Deployment or StatefulSet |
| `kubectl_apply` | Apply a manifest from inline YAML |
| `kubectl_delete` | Delete a resource (DESTRUCTIVE — requires approval) |
| `kubectl_patch` | Patch a resource with a JSON/strategic merge patch |
| `kubectl_create` | Create a resource from inline YAML |
| `kubectl_label` | Add or remove labels |
| `kubectl_annotate` | Add or remove annotations |
| `rollout` | Rollout commands: `status`, `history`, `undo`, `restart` |
| `get_events` | List warning events in a namespace |
| `get_cluster_configuration` | **List all kubeconfig contexts (used for auto-discovery)** |
| `get_api_resources` | List available CRD and core resource kinds |
| `check_service_connectivity` | Test pod-to-service reachability |
| `exec_command` | Run a command inside a pod |

All tools accept an optional `--context` flag. If omitted, the current context is used.

---

## READ Operations (auto-execute, no approval)

```
@opsbot list pods in namespace payments
@opsbot show logs for checkout-api in namespace default
@opsbot get logs for pod checkout-api-7d9f5b-xkq2z last 200 lines
@opsbot describe deployment api-gateway in production cluster
@opsbot list all deployments in namespace default
@opsbot list events in namespace checkout
@opsbot what nodes are in the cluster?
@opsbot list services in namespace default
@opsbot show ingresses in production
@opsbot get rollout history for checkout-api
```

---

## WRITE Operations (execute + post notification)

```
@opsbot scale deployment api-gateway to 5 replicas in namespace production
@opsbot restart deployment checkout-api in namespace default
@opsbot label pod checkout-api-xyz env=debug
@opsbot pause the canary rollout for checkout-api
@opsbot promote the rollout for checkout-api to 100%
```

---

## DESTRUCTIVE Operations (require Slack approval)

```
@opsbot deploy tag v2.1.0 to the production cluster   ← kubectl_apply or helm_upgrade
@opsbot delete namespace staging                        ← requires approval
@opsbot rollback checkout-api to the previous version  ← rollout undo, requires approval
@opsbot drain node ip-10-0-1-42                        ← requires approval
```

When a DESTRUCTIVE tool is triggered, KAGENT creates an Approval CRD. OpsBot's watcher detects it and posts Slack buttons. Clicking Approve patches `status: Approved` on the CRD, which resumes the agent.

---

## Helm tools

The KAGENT tool server also includes Helm tools for release management:

```
@opsbot list helm releases in namespace opsbot
@opsbot upgrade the opsbot chart to 0.3.0
@opsbot show what would change if I upgrade checkout to v2.1.0
```

| Tool | Description |
|---|---|
| `helm_list` | List all releases (namespace-scoped or cluster-wide) |
| `helm_get` | Get release details, values, or manifests |
| `helm_upgrade` | Upgrade a release (WRITE) |
| `helm_install` | Install a new release (WRITE) |
| `helm_uninstall` | Remove a release (DESTRUCTIVE) |

---

## Argo Rollouts

For progressive delivery with Argo Rollouts:

```
@opsbot promote the checkout-api canary to 100%
@opsbot pause the checkout-api rollout
@opsbot set rollout image for checkout-api to v2.1.0
```

| Tool | Description |
|---|---|
| `promote_rollout` | Advance a canary/blue-green rollout |
| `pause_rollout` | Pause a running rollout |
| `set_rollout_image` | Update the container image in a Rollout |
| `verify_argo_rollouts_controller_install` | Check controller health |

> **Note:** These are Argo Rollouts tools (progressive delivery). For ArgoCD GitOps sync operations, use the `shell` tool to call `argocd` CLI, or deploy a custom ArgoCD MCP server.

---

## Risk classification

| Operation | KAGENT tool | Risk |
|---|---|---|
| List pods / describe / logs | `kubectl_get`, `kubectl_logs`, `kubectl_describe` | READ |
| Get events | `get_events` | READ |
| Get rollout history | `rollout history` | READ |
| Scale deployment | `kubectl_scale` | WRITE |
| Restart deployment | `rollout restart` | WRITE |
| Pause / promote rollout | `pause_rollout`, `promote_rollout` | WRITE |
| Apply manifest | `kubectl_apply` | WRITE |
| Delete resource | `kubectl_delete` | DESTRUCTIVE |
| Drain node | `exec_command drain` | DESTRUCTIVE |
| Helm upgrade on production | `helm_upgrade` | DESTRUCTIVE |
