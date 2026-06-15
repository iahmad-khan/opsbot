# Production Helm Deployment

OpsBot ships with a Helm chart at `charts/opsbot/`. It installs: the OpsBot relay pod, the KAGENT controller (as a subchart), the KAGENT tool server (`kagent-tools`), and the custom MCP server pods (GitHub, Datadog, Jira).

---

## Prerequisites

- Helm 3.10+
- Kubernetes 1.27+
- An ingress controller (nginx recommended)
- External PostgreSQL 14+ and Redis 7+

---

## 1. Add Helm OCI registries

```bash
# Verify OCI support (Helm 3.8+ required)
helm version
```

KAGENT uses OCI registries (`oci://ghcr.io/...`), which do not require `helm repo add`.

---

## 2. Fetch subchart dependencies

```bash
helm dependency update charts/opsbot/
```

This pulls:
- `oci://ghcr.io/kagent-dev/kagent/helm/kagent` (KAGENT controller)
- `oci://ghcr.io/kagent-dev/tools/helm/kagent-tools` (tool server)

---

## 3. Create required secrets

```bash
NS=opsbot
kubectl create namespace $NS --dry-run=client -o yaml | kubectl apply -f -

# ── Core secrets ─────────────────────────────────────────────────────────────
kubectl create secret generic opsbot-secrets \
  --from-literal=SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=SLACK_BOT_TOKEN=xoxb-... \
  --from-literal=SLACK_APP_TOKEN=xapp-... \
  --from-literal=SLACK_SIGNING_SECRET=... \
  --from-literal=GITHUB_TOKEN=ghp_... \
  --from-literal=DATABASE_URL=postgresql+asyncpg://opsbot:pass@pg:5432/opsbot \
  --from-literal=REDIS_URL=redis://:pass@redis:6379/0 \
  -n $NS

# ── Kubeconfig — all cluster contexts for auto-discovery ──────────────────────
# Merge all your kubeconfigs into one file first:
KUBECONFIG=~/.kube/prod:~/.kube/staging:~/.kube/dev \
  kubectl config view --flatten > /tmp/merged-kubeconfig

kubectl create secret generic opsbot-kubeconfig \
  --from-file=config=/tmp/merged-kubeconfig \
  -n $NS

# ── Datadog / Jira (if used) ──────────────────────────────────────────────────
kubectl patch secret opsbot-secrets -n $NS \
  --type merge \
  -p '{"stringData":{"DATADOG_API_KEY":"dd-api-...","DATADOG_APP_KEY":"dd-app-..."}}'

kubectl patch secret opsbot-secrets -n $NS \
  --type merge \
  -p '{"stringData":{"JIRA_URL":"https://your-org.atlassian.net","JIRA_USERNAME":"svc-opsbot@company.com","JIRA_API_TOKEN":"your-token"}}'
```

---

## 4. Production `values.yaml`

```yaml
replicaCount: 2

image:
  repository: ghcr.io/your-org/opsbot-backend
  tag: "0.2.0"
  pullPolicy: IfNotPresent

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: opsbot.internal.company.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: opsbot-tls
      hosts:
        - opsbot.internal.company.com

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70

# ── KAGENT controller ─────────────────────────────────────────────────────────
kagent:
  enabled: true
  model: claude-sonnet-4-6

# ── KAGENT tool server ────────────────────────────────────────────────────────
kagent-tools:
  enabled: true
  tools:
    prometheus:
      url: "http://prometheus-server.monitoring.svc.cluster.local:9090"
    grafana:
      url: "http://grafana.monitoring.svc.cluster.local:3000"
      apiKey: ""   # set after Grafana install
    k8s:
      tokenPassthrough: false
    enabledTools: []
  rbac:
    readOnly: false
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 512Mi
  extraVolumes:
    - name: kubeconfig
      secret:
        secretName: opsbot-kubeconfig
        optional: true
  extraVolumeMounts:
    - name: kubeconfig
      mountPath: /root/.kube
      readOnly: true
  extraEnv:
    - name: KUBECONFIG
      value: /root/.kube/config

# ── Custom MCP server images ──────────────────────────────────────────────────
mcpServers:
  github:
    image:
      repository: ghcr.io/github/github-mcp-server
      tag: latest
      pullPolicy: Always
  datadog:
    image:
      repository: ghcr.io/your-org/opsbot-datadog-mcp
      tag: "0.2.0"
    site: datadoghq.com
  jira:
    image:
      repository: ghcr.io/your-org/opsbot-jira-mcp
      tag: "0.2.0"
```

---

## 5. Install

```bash
helm upgrade --install opsbot charts/opsbot/ \
  --namespace opsbot \
  --values charts/opsbot/values.yaml \
  --values production-values.yaml \
  --wait \
  --timeout 10m
```

---

## 6. Run database migrations

```bash
kubectl exec -n opsbot deployment/opsbot-backend -- \
  alembic upgrade head
```

---

## 7. Verify

```bash
# All pods running
kubectl get pods -n opsbot

# KAGENT agents registered
kubectl get agents -n opsbot

# Tool server reachable
kubectl get remotemcpservers -n opsbot

# MCP pods
kubectl get mcpservers -n opsbot

# Cluster contexts discovered
kubectl exec -n opsbot deployment/opsbot-kagent-tools -- \
  wget -qO- http://localhost:8084/mcp
# (Or ask Slack: @opsbot which clusters are configured?)

# OpsBot health
kubectl exec -n opsbot deployment/opsbot-backend -- \
  curl -s localhost:8000/health
```

---

## 8. Access KAGENT UI

```bash
kubectl port-forward svc/kagent-ui 8080:80 -n opsbot
```

Open `http://localhost:8080` — the KAGENT UI shows live agent executions, tool call traces, approval queue, and model config.

---

## Updating clusters (zero-Helm-change)

When you add or remove a cluster:

```bash
# Rebuild merged kubeconfig
KUBECONFIG=~/.kube/prod:~/.kube/staging:~/.kube/dev:~/.kube/new-cluster \
  kubectl config view --flatten > /tmp/merged-kubeconfig

# Replace the secret
kubectl create secret generic opsbot-kubeconfig \
  --from-file=config=/tmp/merged-kubeconfig \
  -n opsbot \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart tool server to pick up new contexts
kubectl rollout restart deployment/opsbot-kagent-tools -n opsbot
```

No `helm upgrade` required.

---

## CI/CD

Add to your release pipeline:

```yaml
# .github/workflows/release.yml
- name: Build and push backend
  run: |
    docker build -t ghcr.io/${{ github.repository_owner }}/opsbot-backend:${{ github.ref_name }} \
      -f backend/Dockerfile backend/
    docker push ghcr.io/${{ github.repository_owner }}/opsbot-backend:${{ github.ref_name }}

- name: Build and push custom MCP servers
  run: |
    for srv in datadog-mcp jira-mcp; do
      docker build -t ghcr.io/${{ github.repository_owner }}/opsbot-$srv:${{ github.ref_name }} \
        mcp-servers/$srv/
      docker push ghcr.io/${{ github.repository_owner }}/opsbot-$srv:${{ github.ref_name }}
    done

- name: Helm upgrade
  run: |
    helm dependency update charts/opsbot/
    helm upgrade --install opsbot charts/opsbot/ \
      --namespace opsbot \
      --set image.tag=${{ github.ref_name }} \
      --set mcpServers.datadog.image.tag=${{ github.ref_name }} \
      --set mcpServers.jira.image.tag=${{ github.ref_name }} \
      --wait
```

Note: `kagent-tools` uses KAGENT's official image and is not rebuilt by your pipeline.

---

## Rollback

```bash
# OpsBot relay only
helm rollback opsbot -n opsbot

# Or target a specific revision
helm history opsbot -n opsbot
helm rollback opsbot <revision> -n opsbot
```
