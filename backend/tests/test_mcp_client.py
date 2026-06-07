"""Tests for MCP client — secret redaction."""
from __future__ import annotations

from opsbot.mcp.client import _redact_args


class TestRedactArgs:
    def test_redacts_token(self):
        result = _redact_args({"token": "ghp_secret123", "namespace": "prod"})
        assert result["token"] == "***"
        assert result["namespace"] == "prod"

    def test_redacts_password(self):
        result = _redact_args({"password": "s3cr3t", "user": "alice"})
        assert result["password"] == "***"
        assert result["user"] == "alice"

    def test_redacts_api_key(self):
        result = _redact_args({"api_key": "dd-abc123", "query": "avg:system.cpu{*}"})
        assert result["api_key"] == "***"
        assert result["query"] == "avg:system.cpu{*}"

    def test_non_sensitive_keys_unchanged(self):
        result = _redact_args({"deployment": "checkout", "image": "checkout:v2.0.0", "namespace": "default"})
        assert result == {"deployment": "checkout", "image": "checkout:v2.0.0", "namespace": "default"}

    def test_empty_dict(self):
        assert _redact_args({}) == {}

    def test_key_partially_matching(self):
        # "auth_token" contains "token" — should be redacted
        result = _redact_args({"auth_token": "secret"})
        assert result["auth_token"] == "***"
