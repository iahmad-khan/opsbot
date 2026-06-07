# Production Helm Deployment

OpsBot ships with a Helm chart at `charts/opsbot/`. This guide covers a production-grade deployment.

---

## Prerequisites

- Helm 3.x
- A Kubernetes cluster with an ingress controller
- Container registry (ECR, GCR, Docker Hub, etc.)
- PostgreSQL 14+ (external or in-cluster)
- Redis 7+ (external or in-cluster)

---

## Quick Install

```bash
helm upgrade --install opsbot charts/opsbot/ \
  --namespace opsbot \
  --create-namespace \
  --values charts/opsbot/values.yaml \
  --set image.backend.tag=0.1.0 \
  --set image.worker.tag=0.1.0 \
  --set image.frontend.tag=0.1.0 \
  -f production-values.yaml
```

---

## Required Secrets

Create these Kubernetes secrets before installing:

```bash
# Application secrets
kubectl create secret generic opsbot-secrets \
  --from-literal=SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=SLACK_BOT_TOKEN=xoxb-... \
  --from-literal=SLACK_APP_TOKEN=xapp-... \
  --from-literal=SLACK_SIGNING_SECRET=... \
  --from-literal=GITHUB_TOKEN=ghp_... \
  --from-literal=DASHBOARD_SECRET=your-secure-password \
  -n opsbot

# Kubeconfig (needed for K8s tool access)
kubectl create secret generic opsbot-kubeconfig \
  --from-file=config=$HOME/.kube/config \
  -n opsbot

# PostgreSQL password
kubectl create secret generic opsbot-postgres \
  --from-literal=password=pg-password \
  -n opsbot

# Redis auth
kubectl create secret generic opsbot-redis \
  --from-literal=password=redis-password \
  -n opsbot
```

---

## Production values.yaml

```yaml
image:
  backend:
    repository: your-registry/opsbot-backend
    tag: "0.1.0"
    pullPolicy: IfNotPresent
  worker:
    repository: your-registry/opsbot-worker
    tag: "0.1.0"
  frontend:
    repository: your-registry/opsbot-frontend
    tag: "0.1.0"

# Backend replicas
replicaCount: 2
workerReplicas: 3
worker:
  concurrency: 8

# Frontend replicas (HPA in hpa.yaml scales automatically)
frontend:
  replicaCount: 2

# Database (external managed PostgreSQL)
postgresql:
  enabled: false  # Use external PG
  externalHost: "postgres.your-domain.com"
  port: 5432
  database: opsbot
  user: opsbot
  existingSecret: opsbot-postgres
  existingSecretPasswordKey: password

# Redis (external managed Redis)
redis:
  enabled: true
  auth:
    enabled: true
    existingSecret: opsbot-redis
    existingSecretPasswordKey: password
  master:
    persistence:
      enabled: true
      size: 8Gi

# Ingress
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: opsbot.your-domain.com
      paths:
        - path: /
          service: frontend
        - path: /api
          service: backend
        - path: /slack
          service: backend
  tls:
    - secretName: opsbot-tls
      hosts:
        - opsbot.your-domain.com

# Resource limits
resources:
  backend:
    requests: { cpu: "200m", memory: "256Mi" }
    limits:   { cpu: "1000m", memory: "1Gi" }
  worker:
    requests: { cpu: "500m", memory: "512Mi" }
    limits:   { cpu: "2000m", memory: "2Gi" }

# HPA
autoscaling:
  backend:
    enabled: true
    minReplicas: 2
    maxReplicas: 5
    targetCPUUtilizationPercentage: 70
  worker:
    enabled: true
    minReplicas: 2
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70
```

---

## Database Migrations

Migrations run as a **pre-install/pre-upgrade Helm Hook Job** (not an initContainer). This ensures only one migration runs per deploy, even with multiple backend replicas:

```yaml
# charts/opsbot/templates/job-migrate.yaml
annotations:
  "helm.sh/hook": pre-install,pre-upgrade
  "helm.sh/hook-weight": "-5"
  "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

If the migration job fails, the Helm upgrade is blocked. Fix the migration, delete the failed job, and retry:

```bash
kubectl delete job -n opsbot opsbot-db-migrate
helm upgrade opsbot charts/opsbot/ --namespace opsbot ...
```

---

## Celery Beat (Scheduler)

The `beat` Deployment runs redbeat, a distributed Celery Beat backed by Redis. It prevents double-firing on pod restart. Only **one beat pod** should run at a time — set `beat.replicas: 1` in values.yaml.

---

## Caveats

- **`NEXTAUTH_URL`** in the frontend deployment must match the public URL of your ingress host.
- **kubeconfig Secret.** The backend and worker pods need the kubeconfig mounted. Update the chart's volume configuration if using a different secret name.
- **Redis DB separation.** OpsBot uses three Redis DBs: 0 (app data), 1 (Celery broker), 2 (Celery results). Ensure your managed Redis instance allows multiple DBs (some managed services restrict this).
- **Flower** (Celery monitoring) is included in docker-compose but not in the Helm chart by default. Deploy separately if needed: `kubectl port-forward svc/opsbot-flower 5555:5555 -n opsbot`.
- **OpenAPI docs are disabled in production.** `APP_ENV=production` disables `/docs`, `/redoc`, and `/openapi.json` to reduce attack surface.
- **Worker liveness probe** uses `celery inspect ping`, which can be slow on cold start. Increase the `initialDelaySeconds` if workers are being killed before they've warmed up.
