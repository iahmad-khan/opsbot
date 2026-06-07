from __future__ import annotations

import os
from dataclasses import dataclass, field

from opsbot.config.settings import get_settings


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    description: str = ""


def get_server_configs() -> list[MCPServerConfig]:
    s = get_settings()
    configs: list[MCPServerConfig] = []

    # Kubernetes MCP Server
    configs.append(MCPServerConfig(
        name="kubernetes",
        command=s.mcp_kubernetes_command.split()[0],
        args=s.mcp_kubernetes_command.split()[1:],
        env={
            "KUBECONFIG": os.path.expanduser(s.kubeconfig_path),
        },
        description="Kubernetes cluster operations",
    ))

    # GitHub MCP Server
    if s.github_token:
        configs.append(MCPServerConfig(
            name="github",
            command=s.mcp_github_command.split()[0],
            args=s.mcp_github_command.split()[1:],
            env={
                "GITHUB_PERSONAL_ACCESS_TOKEN": s.github_token,
            },
            description="GitHub repository and user management",
        ))

    # Terraform MCP Server
    if s.tfe_token or os.path.exists(s.terraform_working_dir):
        cmd_parts = s.mcp_terraform_command.split()
        configs.append(MCPServerConfig(
            name="terraform",
            command=cmd_parts[0],
            args=cmd_parts[1:],
            env={
                "TFE_TOKEN": s.tfe_token,
                "TERRAFORM_WORKING_DIR": s.terraform_working_dir,
            },
            description="Terraform plan and apply operations",
        ))

    # ArgoCD MCP Server
    if s.argocd_server_url:
        cmd_parts = s.mcp_argocd_command.split()
        configs.append(MCPServerConfig(
            name="argocd",
            command=cmd_parts[0],
            args=cmd_parts[1:],
            env={
                "ARGOCD_SERVER": s.argocd_server_url,
                "ARGOCD_TOKEN": s.argocd_token,
                "ARGOCD_INSECURE": str(s.argocd_insecure).lower(),
            },
            description="ArgoCD application sync and rollback",
        ))

    # Prometheus MCP Server
    if s.prometheus_url:
        cmd_parts = s.mcp_prometheus_command.split()
        configs.append(MCPServerConfig(
            name="prometheus",
            command=cmd_parts[0],
            args=cmd_parts[1:],
            env={
                "PROMETHEUS_URL": s.prometheus_url,
            },
            description="Prometheus metrics queries and alerting",
        ))

    # DataDog MCP Server
    if s.datadog_api_key:
        cmd_parts = s.mcp_datadog_command.split()
        configs.append(MCPServerConfig(
            name="datadog",
            command=cmd_parts[0],
            args=cmd_parts[1:],
            env={
                "DD_API_KEY": s.datadog_api_key,
                "DD_APP_KEY": s.datadog_app_key,
                "DD_SITE": s.datadog_site,
            },
            description="DataDog metrics, logs, and monitors",
        ))

    return [c for c in configs if c.enabled]
