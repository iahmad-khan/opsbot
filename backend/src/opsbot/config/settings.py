from __future__ import annotations

import warnings
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "OpsBot"
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = Field(default=["http://localhost:3000"])
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # LLM
    litellm_default_model: str = "claude-sonnet-4-6"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    litellm_max_tokens: int = 8192
    litellm_temperature: float = 0.0
    litellm_max_retries: int = 3
    litellm_timeout: int = 120

    # Slack
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_signing_secret: str = ""
    slack_default_channel: str = "#ops-bot"

    # Database
    database_url: str = "postgresql+asyncpg://opsbot:opsbot@localhost:5432/opsbot"
    database_url_sync: str = "postgresql://opsbot:opsbot@localhost:5432/opsbot"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    conversation_context_ttl: int = 86400  # 24 hours in seconds
    conversation_max_messages: int = 20

    # GitHub
    github_token: str = ""
    github_org: str = ""

    # Kubernetes
    kubeconfig_path: str = "~/.kube/config"
    k8s_default_namespace: str = "default"

    # ArgoCD
    argocd_server_url: str = ""
    argocd_token: str = ""
    argocd_insecure: bool = False

    # Terraform
    terraform_working_dir: str = "/app/workdir/terraform"
    tfe_token: str = ""

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # GCP
    google_application_credentials: str = ""
    gcp_project: str = ""

    # Azure
    azure_subscription_id: str = ""
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # Observability
    prometheus_url: str = "http://localhost:9090"
    grafana_url: str = "http://localhost:3001"
    grafana_token: str = ""

    datadog_api_key: str = ""
    datadog_app_key: str = ""
    datadog_site: str = "datadoghq.com"

    pagerduty_api_key: str = ""
    pagerduty_from_email: str = ""

    opsgenie_api_key: str = ""

    # Bitbucket (Cloud or Server)
    bitbucket_url: str = "https://api.bitbucket.org/2.0"
    bitbucket_username: str = ""
    bitbucket_app_password: str = ""  # Cloud: app password; Server: use bitbucket_token
    bitbucket_token: str = ""         # Server PAT or OAuth token
    bitbucket_workspace: str = ""

    # GitLab (Cloud or self-hosted)
    gitlab_url: str = "https://gitlab.com"
    gitlab_token: str = ""
    gitlab_default_group: str = ""

    # Jira (Cloud or Server/Data Center)
    jira_url: str = ""
    jira_username: str = ""   # Cloud: email address; Server: username
    jira_api_token: str = ""  # Cloud: API token; Server: password or PAT
    jira_default_project: str = ""

    # Confluence (Cloud or Server/Data Center)
    confluence_url: str = ""
    confluence_username: str = ""   # Cloud: email address; Server: username
    confluence_api_token: str = ""  # Cloud: API token; Server: password or PAT
    confluence_default_space: str = ""

    # OpenSearch / Elasticsearch
    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_api_key: str = ""
    opensearch_default_index: str = "logs-*"
    opensearch_verify_ssl: bool = True

    # RBAC
    default_approver_slack_ids: list[str] = Field(default=[])
    default_user_role: str = "developer"
    approval_timeout_minutes: int = 30
    require_dual_approval_for: list[str] = Field(
        default=["delete_namespace", "drop_database"]
    )

    # Multi-cluster Kubernetes
    # Comma-separated kubeconfig context names to expose as separate MCP servers.
    # When set, tools are namespaced as kubernetes-<ctx>__<tool>.
    # When empty, a single "kubernetes" server is started using the active context.
    k8s_contexts: list[str] = Field(default=[])

    # Web dashboard authentication
    # Set a non-empty secret to require a password on the Next.js dashboard.
    # Leave empty to skip auth (suitable for local dev behind a firewall).
    dashboard_secret: str = ""

    # Deployment freeze windows
    # Comma-separated ISO weekday numbers (0=Mon … 6=Sun) on which DESTRUCTIVE ops
    # are blocked. Leave empty to disable freeze-window enforcement.
    freeze_deployment_days: list[int] = Field(default=[])
    # UTC hour (0–23) at which the freeze starts; -1 = all day on freeze_deployment_days.
    freeze_deployment_start_utc: int = -1
    # UTC hour (0–23) at which the freeze ends; supports overnight windows (e.g. start=22, end=6).
    freeze_deployment_end_utc: int = -1
    freeze_deployment_message: str = (
        "Deployment freeze is currently active. "
        "Contact an admin for emergency overrides."
    )

    # MCP tool execution
    tool_timeout_seconds: int = 30  # per-tool call timeout; prevents slow integrations from stalling workers

    # LLM cost guardrails
    litellm_daily_token_limit: int = 100_000  # per-user daily token budget (0 = unlimited)

    # Audit log retention
    audit_log_retention_days: int = 90  # rows older than this are purged nightly by beat

    # MCP server commands
    mcp_kubernetes_command: str = "npx -y kubernetes-mcp-server@latest"
    mcp_github_command: str = "npx -y @modelcontextprotocol/server-github"
    mcp_terraform_command: str = "docker run --rm -i hashicorp/terraform-mcp-server:0.4.0"
    mcp_argocd_command: str = "node /app/mcp-servers/argocd-mcp/dist/index.js"
    mcp_prometheus_command: str = "node /app/mcp-servers/prometheus-mcp/dist/index.js"
    mcp_datadog_command: str = "node /app/mcp-servers/datadog-mcp/dist/index.js"
    mcp_opensearch_command: str = "node /app/mcp-servers/opensearch-mcp/dist/index.js"
    mcp_bitbucket_command: str = "node /app/mcp-servers/bitbucket-mcp/dist/index.js"
    mcp_gitlab_command: str = "node /app/mcp-servers/gitlab-mcp/dist/index.js"
    mcp_jira_command: str = "node /app/mcp-servers/jira-mcp/dist/index.js"
    mcp_confluence_command: str = "node /app/mcp-servers/confluence-mcp/dist/index.js"

    @field_validator("cors_origins", "default_approver_slack_ids", "require_dual_approval_for", "k8s_contexts", mode="before")
    @classmethod
    def split_comma(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("freeze_deployment_days", mode="before")
    @classmethod
    def parse_int_list(cls, v: str | list) -> list[int]:
        if isinstance(v, str):
            return [int(p.strip()) for p in v.split(",") if p.strip().lstrip("-").isdigit()]
        return [int(x) for x in v]

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        _default_key = "change-me-in-production"
        if self.secret_key == _default_key:
            if self.app_env == "production":
                raise ValueError(
                    "SECRET_KEY must be set to a secure random value in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            warnings.warn(
                "SECRET_KEY is using the insecure default. Set SECRET_KEY in your .env file.",
                stacklevel=2,
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def redis_session_url(self) -> str:
        return self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
