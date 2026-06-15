"""Tests for RBAC logic and tool risk classification (KAGENT-aware)."""
from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")

from opsbot.models.db import RiskLevel
from opsbot.tools.registry import get_tool_risk


class TestToolRiskMap:
    def test_k8s_deploy_is_destructive(self):
        assert get_tool_risk("k8s_deploy_image") == RiskLevel.DESTRUCTIVE

    def test_k8s_logs_is_read(self):
        assert get_tool_risk("k8s_get_pod_logs") == RiskLevel.READ

    def test_k8s_scale_is_write(self):
        assert get_tool_risk("k8s_scale_deployment") == RiskLevel.WRITE

    def test_argocd_sync_is_destructive(self):
        assert get_tool_risk("argocd_sync") == RiskLevel.DESTRUCTIVE

    def test_terraform_apply_is_destructive(self):
        assert get_tool_risk("terraform_apply") == RiskLevel.DESTRUCTIVE

    def test_terraform_plan_is_read(self):
        assert get_tool_risk("terraform_plan") == RiskLevel.READ

    def test_github_trigger_workflow_is_write(self):
        assert get_tool_risk("github_trigger_workflow") == RiskLevel.WRITE

    def test_pagerduty_resolve_is_destructive(self):
        assert get_tool_risk("pagerduty_resolve") == RiskLevel.DESTRUCTIVE

    def test_unknown_tool_defaults_to_write(self):
        assert get_tool_risk("some_unregistered_tool") == RiskLevel.WRITE

    def test_mcp_prefixed_tool_resolved(self):
        # Tools from MCP servers arrive as "kubernetes__k8s_list_pods" — the part after __ is used.
        assert get_tool_risk("kubernetes__k8s_get_pod_logs") == RiskLevel.READ

    def test_argocd_rollback_destructive(self):
        assert get_tool_risk("argocd_rollback") == RiskLevel.DESTRUCTIVE


class TestIntentDetection:
    def test_slo_intent(self):
        from opsbot.agent.router import Intent, detect_intent
        result = detect_intent("analyze checkout-service and propose SLOs")
        assert result.intent == Intent.SLO_ANALYSIS

    def test_rca_intent(self):
        from opsbot.agent.router import Intent, detect_intent
        result = detect_intent("root cause of the payment-api failure last night")
        assert result.intent == Intent.RCA

    def test_general_ops_intent(self):
        from opsbot.agent.router import Intent, detect_intent
        result = detect_intent("deploy tag v1.2.3 to uat")
        assert result.intent == Intent.GENERAL_OPS

    def test_service_name_extracted(self):
        from opsbot.agent.router import detect_intent
        result = detect_intent("analyze checkout-service and propose SLOs")
        assert result.service_name == "checkout-service"

    def test_namespace_extracted(self):
        from opsbot.agent.router import detect_intent
        result = detect_intent("root cause of failures in namespace production")
        assert result.namespace == "production"
