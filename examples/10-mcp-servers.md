# MCP Servers and KAGENT Tool Server

OpsBot uses KAGENT's official tool server for the majority of DevOps tools. Two custom MCP servers cover integrations not yet in KAGENT's bundled server.

---

## KAGENT official tool server

**Image:** `ghcr.io/kagent-dev/kagent/tools` · **Port:** 8084 · **Protocol:** MCP over HTTP/SSE

The KAGENT tool server is deployed as the `kagent-tools` subchart and exposed to agents via a `RemoteMCPServer` CRD. It replaces what previously required 5+ separate MCP server pods.

### Bundled tool categories

| Category | Key tools |
|---|---|
| **Kubernetes** | `kubectl_get`, `kubectl_logs`, `kubectl_scale`, `kubectl_apply`, `kubectl_delete`, `kubectl_patch`, `rollout`, `get_events`, `get_cluster_configuration`, `exec_command`, `check_service_connectivity` |
| **Helm** | `helm_list`, `helm_get`, `helm_upgrade`, `helm_install`, `helm_uninstall`, `helm_repo_add` |
| **Argo Rollouts** | `promote_rollout`, `pause_rollout`, `set_rollout_image`, `verify_argo_rollouts_controller_install` |
| **Prometheus** | `prometheus_query`, `prometheus_range_query`, `prometheus_labels`, `prometheus_targets` |
| **Grafana** | `grafana_dashboard_management`, `grafana_alert_management`, `grafana_datasource_management` |
| **Cilium** | `cilium_status_and_version`, `upgrade_cilium`, `connect_to_remote_cluster`, `toggle_hubble` |
| **Istio** | `istio_analyze`, `istio_proxy_status`, `istio_proxy_config`, `istio_waypoint_*` |
| **Shell** | `shell` — run arbitrary shell commands (e.g., `argocd` CLI, `terraform`, `aws`) |
| **DateTime** | `current_date_time`, `format_time`, `parse_time` |

### Configuration

All configuration for the KAGENT tool server lives under the `kagent-tools:` key in `values.yaml`:

```yaml
kagent-tools:
  enabled: true
  tools:
    prometheus:
      url: "http://prometheus.monitoring.svc.cluster.local:9090"
    grafana:
      url: "http://grafana.monitoring.svc.cluster.local:3000"
      apiKey: ""        # Grafana service-account token
    k8s:
      tokenPassthrough: false
    enabledTools: []    # empty = all categories enabled
  rbac:
    readOnly: false     # true = deploy read-only ClusterRole
  # Kubeconfig for multi-cluster access (see examples/03-kubernetes.md)
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

### Verify the tool server is running

```bash
kubectl get pods -n opsbot -l app=kagent-tools
kubectl logs -n opsbot deployment/opsbot-kagent-tools | tail -20

# Check registered tools via Prometheus metrics
kubectl port-forward svc/opsbot-kagent-tools 8084:8084 -n opsbot
curl -s http://localhost:8084/metrics | grep kagent_tools_mcp_registered_tools
```

---

## Custom MCP servers

Two integrations still require custom pods because KAGENT does not yet publish official images for them.

### GitHub MCP server

Uses the official server published by GitHub, Inc.:

```yaml
mcpServers:
  github:
    image:
      repository: ghcr.io/github/github-mcp-server
      tag: latest
```

Required secret key: `GITHUB_TOKEN` in the `opsbot-secrets` K8s Secret.

```
@opsbot list open PRs in backend repo
@opsbot create a PR from feature/fix to main in backend repo
@opsbot check CI status for the latest commit on main
@opsbot add john to backend-api with write access
```

### Datadog MCP server

Custom TypeScript server in `mcp-servers/datadog-mcp/`. Required secret keys: `DATADOG_API_KEY`, `DATADOG_APP_KEY`.

```
@opsbot check monitors for payment-service
@opsbot mute the checkout-api latency monitor for 2 hours
@opsbot query metrics for p99 latency of checkout-service last 1 hour
```

### Jira MCP server

Custom TypeScript server in `mcp-servers/jira-mcp/`. Required secret keys: `JIRA_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`.

```
@opsbot create a high-priority bug: "payment-service timeout in prod"
@opsbot show my open tickets
@opsbot transition PROJ-123 to In Review
@opsbot assign PROJ-456 to alice
```

---

## How tools are wired to agents

Each Agent CRD declares which tools it uses. The `opsbot-general` agent references all sources:

```yaml
tools:
  # KAGENT bundled tool server (kubectl, helm, prometheus, ...)
  - type: McpServer
    mcpServer:
      name: opsbot-kagent-tools
      kind: RemoteMCPServer
      apiGroup: kagent.dev
      toolNames:
        - kubectl_get
        - kubectl_logs
        - prometheus_query
        # ... (see charts/opsbot/templates/kagent/agents.yaml)

  - type: McpServer
    mcpServer:
      name: github-mcp
      kind: MCPServer
      apiGroup: kagent.dev

  - type: McpServer
    mcpServer:
      name: datadog-mcp
      kind: MCPServer
      apiGroup: kagent.dev

  - type: McpServer
    mcpServer:
      name: jira-mcp
      kind: MCPServer
      apiGroup: kagent.dev
```

Inspect live tool registration:

```bash
kubectl get remotemcpservers,mcpservers -n opsbot
kubectl describe agent opsbot-general -n opsbot
```

---

## Adding a new integration

### Option A — use the `shell` tool (fastest)

The `shell` tool can run any binary in the KAGENT tool server pod. For CLIs with simple interfaces (ArgoCD, AWS, gcloud), this avoids building a custom MCP server:

```
@opsbot run: argocd app sync checkout-app --grpc-web
@opsbot run: terraform plan -no-color in /workspace/infra/staging
```

Install extra CLIs by building a custom tool server image:

```dockerfile
FROM ghcr.io/kagent-dev/kagent/tools:latest
RUN apt-get update && apt-get install -y curl && \
    curl -sSL -o /usr/local/bin/argocd \
      https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64 && \
    chmod +x /usr/local/bin/argocd
```

Override the image in `values.yaml`:

```yaml
kagent-tools:
  image:
    registry: ghcr.io
    repository: your-org/opsbot-tools
    tag: "0.2.0"
```

### Option B — deploy a custom MCPServer CRD

For richer structured tool definitions, add a new `MCPServer` entry to `charts/opsbot/templates/kagent/mcp-servers.yaml`:

```yaml
---
apiVersion: kagent.dev/v1alpha1
kind: MCPServer
metadata:
  name: argocd-mcp
  namespace: {{ .Release.Namespace }}
spec:
  podTemplate:
    spec:
      containers:
        - name: server
          image: "your-registry/argocd-mcp:latest"
          env:
            - name: ARGOCD_SERVER_URL
              valueFrom:
                secretKeyRef:
                  name: opsbot-secrets
                  key: ARGOCD_SERVER_URL
```

Then add it to the agent's `tools` list in `agents.yaml`.

---

## Tool server resource limits

```yaml
kagent-tools:
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 1000m
      memory: 512Mi
```
