from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Awaitable

import structlog

from opsbot.models.db import RiskLevel

log = structlog.get_logger(__name__)

# Maps tool_name → risk level for the approval engine
TOOL_RISK_MAP: dict[str, str] = {
    # === READ ===
    "k8s_list_pods": RiskLevel.READ,
    "k8s_get_pod_logs": RiskLevel.READ,
    "k8s_get_pod": RiskLevel.READ,
    "k8s_list_deployments": RiskLevel.READ,
    "k8s_get_deployment": RiskLevel.READ,
    "k8s_list_events": RiskLevel.READ,
    "k8s_get_namespace": RiskLevel.READ,
    "k8s_list_namespaces": RiskLevel.READ,
    "k8s_describe_node": RiskLevel.READ,
    "k8s_list_nodes": RiskLevel.READ,
    "k8s_list_services": RiskLevel.READ,
    "k8s_list_ingresses": RiskLevel.READ,
    "k8s_list_configmaps": RiskLevel.READ,
    "k8s_get_hpa": RiskLevel.READ,
    "github_list_repos": RiskLevel.READ,
    "github_list_members": RiskLevel.READ,
    "github_get_pr": RiskLevel.READ,
    "github_list_prs": RiskLevel.READ,
    "github_get_ci_status": RiskLevel.READ,
    "argocd_list_apps": RiskLevel.READ,
    "argocd_get_app": RiskLevel.READ,
    "argocd_get_app_history": RiskLevel.READ,
    "terraform_plan": RiskLevel.READ,
    "terraform_show_state": RiskLevel.READ,
    "aws_list_eks_clusters": RiskLevel.READ,
    "aws_list_ecr_images": RiskLevel.READ,
    "aws_describe_ec2": RiskLevel.READ,
    "aws_list_iam_users": RiskLevel.READ,
    "gcp_list_clusters": RiskLevel.READ,
    "gcp_list_images": RiskLevel.READ,
    "azure_list_clusters": RiskLevel.READ,
    "prometheus_query": RiskLevel.READ,
    "prometheus_query_range": RiskLevel.READ,
    "prometheus_list_alerts": RiskLevel.READ,
    "grafana_list_dashboards": RiskLevel.READ,
    "grafana_get_dashboard_url": RiskLevel.READ,
    "pagerduty_list_incidents": RiskLevel.READ,
    "pagerduty_get_oncall": RiskLevel.READ,
    "opsgenie_list_alerts": RiskLevel.READ,
    "opsgenie_get_oncall": RiskLevel.READ,
    "datadog_query_metrics": RiskLevel.READ,
    "datadog_get_logs": RiskLevel.READ,
    "datadog_list_monitors": RiskLevel.READ,

    # === WRITE ===
    "k8s_restart_deployment": RiskLevel.WRITE,
    "k8s_scale_deployment": RiskLevel.WRITE,
    "k8s_patch_configmap": RiskLevel.WRITE,
    "k8s_cordon_node": RiskLevel.WRITE,
    "k8s_uncordon_node": RiskLevel.WRITE,
    "github_add_member": RiskLevel.WRITE,
    "github_remove_member": RiskLevel.WRITE,
    "github_create_pr": RiskLevel.WRITE,
    "github_create_branch": RiskLevel.WRITE,
    "github_create_issue": RiskLevel.WRITE,
    "argocd_refresh_app": RiskLevel.WRITE,
    "pagerduty_acknowledge": RiskLevel.WRITE,
    "pagerduty_create_incident": RiskLevel.WRITE,
    "opsgenie_acknowledge": RiskLevel.WRITE,
    "prometheus_silence_alert": RiskLevel.WRITE,
    "grafana_create_annotation": RiskLevel.WRITE,
    "aws_add_iam_user_to_group": RiskLevel.WRITE,

    # === DESTRUCTIVE ===
    "k8s_deploy_image": RiskLevel.DESTRUCTIVE,
    "k8s_rollback_deployment": RiskLevel.DESTRUCTIVE,
    "k8s_delete_pod": RiskLevel.DESTRUCTIVE,
    "k8s_delete_namespace": RiskLevel.DESTRUCTIVE,
    "k8s_drain_node": RiskLevel.DESTRUCTIVE,
    "argocd_sync": RiskLevel.DESTRUCTIVE,
    "argocd_rollback": RiskLevel.DESTRUCTIVE,
    "argocd_delete_app": RiskLevel.DESTRUCTIVE,
    "terraform_apply": RiskLevel.DESTRUCTIVE,
    "terraform_destroy": RiskLevel.DESTRUCTIVE,
    "aws_update_ecr_policy": RiskLevel.DESTRUCTIVE,
    "aws_delete_iam_user": RiskLevel.DESTRUCTIVE,
    "pagerduty_resolve": RiskLevel.DESTRUCTIVE,
}


def get_tool_risk(tool_name: str) -> str:
    # also handle MCP-prefixed tools like "kubernetes__list_pods"
    base = tool_name.split("__")[-1] if "__" in tool_name else tool_name
    return TOOL_RISK_MAP.get(tool_name, TOOL_RISK_MAP.get(base, RiskLevel.WRITE))


def get_human_description(tool_name: str, args: dict) -> str:
    """Generate a human-readable description for approval messages."""
    descriptions: dict[str, Callable[[dict], str]] = {
        "k8s_deploy_image": lambda a: f"Deploy image `{a.get('image')}` to deployment `{a.get('deployment')}` in `{a.get('namespace', 'default')}`",
        "k8s_rollback_deployment": lambda a: f"Rollback deployment `{a.get('deployment')}` in `{a.get('namespace', 'default')}` to revision `{a.get('revision', 'previous')}`",
        "k8s_delete_pod": lambda a: f"Delete pod `{a.get('pod_name')}` in `{a.get('namespace', 'default')}`",
        "k8s_delete_namespace": lambda a: f"⚠️ DELETE namespace `{a.get('namespace')}` and ALL its resources",
        "k8s_restart_deployment": lambda a: f"Rolling restart deployment `{a.get('deployment')}` in `{a.get('namespace', 'default')}`",
        "k8s_scale_deployment": lambda a: f"Scale deployment `{a.get('deployment')}` to `{a.get('replicas')}` replicas in `{a.get('namespace', 'default')}`",
        "k8s_drain_node": lambda a: f"Drain node `{a.get('node_name')}` (evicts all pods)",
        "argocd_sync": lambda a: f"Sync ArgoCD application `{a.get('app_name')}`",
        "argocd_rollback": lambda a: f"Rollback ArgoCD application `{a.get('app_name')}` to revision `{a.get('revision', 'previous')}`",
        "terraform_apply": lambda a: f"Terraform apply in workspace `{a.get('workspace', 'default')}` ({a.get('plan_file', 'latest plan')})",
        "terraform_destroy": lambda a: f"⚠️ TERRAFORM DESTROY in workspace `{a.get('workspace', 'default')}`",
        "github_add_member": lambda a: f"Add `{a.get('username')}` to GitHub repo `{a.get('repo')}` with `{a.get('permission', 'read')}` access",
        "github_remove_member": lambda a: f"Remove `{a.get('username')}` from GitHub repo `{a.get('repo')}`",
        "github_create_pr": lambda a: f"Create PR `{a.get('title')}` in `{a.get('repo')}`",
    }
    base = tool_name.split("__")[-1] if "__" in tool_name else tool_name
    fn = descriptions.get(tool_name, descriptions.get(base))
    if fn:
        return fn(args)
    return f"Execute `{tool_name}` with args: {args}"
