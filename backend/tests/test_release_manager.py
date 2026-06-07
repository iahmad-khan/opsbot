"""Tests for the release manager tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from opsbot.tools.release_manager import ReleaseManager, _parse_image_tag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestParseImageTag:
    def test_with_tag(self):
        name, tag = _parse_image_tag("registry.io/myapp:v1.2.3")
        assert tag == "v1.2.3"

    def test_without_tag(self):
        name, tag = _parse_image_tag("registry.io/myapp")
        assert tag == "latest"

    def test_latest_explicit(self):
        name, tag = _parse_image_tag("nginx:latest")
        assert tag == "latest"


# ---------------------------------------------------------------------------
# compare_environments
# ---------------------------------------------------------------------------

class TestCompareEnvironments:
    @pytest.mark.asyncio
    async def test_in_sync(self):
        rm = ReleaseManager()
        same_status = {
            "deployments": [
                {"source": "kubernetes", "tag": "v1.2.3", "image_tags": []},
            ]
        }
        with patch.object(rm, "get_release_status", AsyncMock(return_value=same_status)):
            result = await rm.compare_environments("checkout", "staging", "production")

        assert result["in_sync"] is True
        assert "v1.2.3" in result["summary"]

    @pytest.mark.asyncio
    async def test_out_of_sync(self):
        rm = ReleaseManager()
        staging_status = {"deployments": [{"tag": "v1.3.0", "image_tags": []}]}
        prod_status = {"deployments": [{"tag": "v1.2.9", "image_tags": []}]}

        async def fake_status(service, environment=None):
            return staging_status if environment == "staging" else prod_status

        with patch.object(rm, "get_release_status", AsyncMock(side_effect=fake_status)):
            result = await rm.compare_environments("checkout", "staging", "production")

        assert result["in_sync"] is False
        assert result["staging"] == ["v1.3.0"]
        assert result["production"] == ["v1.2.9"]


# ---------------------------------------------------------------------------
# get_release_diff
# ---------------------------------------------------------------------------

class TestGetReleaseDiff:
    @pytest.mark.asyncio
    async def test_github_diff(self):
        mock_data = {
            "total_commits": 3,
            "status": "ahead",
            "html_url": "https://github.com/org/repo/compare/v1.2.3...v1.2.4",
            "commits": [
                {"sha": "abc123def456", "commit": {"message": "Fix bug", "author": {"name": "Alice", "date": "2026-06-01"}}},
            ],
            "files": [
                {"filename": "src/main.py", "changes": 10, "status": "modified"},
            ],
        }

        import httpx
        with patch("opsbot.tools.release_manager.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_class:
            mock_settings.return_value.github_token = "ghp_test"
            mock_settings.return_value.github_org = "myorg"
            mock_settings.return_value.gitlab_token = ""

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_data
            mock_response.raise_for_status = MagicMock()

            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_http

            rm = ReleaseManager()
            result = await rm.get_release_diff("myapp", "v1.2.3", "v1.2.4")

        assert result["source"] == "github"
        assert result["from_tag"] == "v1.2.3"
        assert result["to_tag"] == "v1.2.4"

    @pytest.mark.asyncio
    async def test_no_token_returns_error(self):
        with patch("opsbot.tools.release_manager.get_settings") as mock_settings:
            mock_settings.return_value.github_token = ""
            mock_settings.return_value.gitlab_token = ""
            mock_settings.return_value.github_org = ""
            mock_settings.return_value.gitlab_default_group = ""

            rm = ReleaseManager()
            result = await rm.get_release_diff("myapp", "v1.0.0", "v1.1.0")

        assert "error" in result


# ---------------------------------------------------------------------------
# get_promotion_plan
# ---------------------------------------------------------------------------

class TestGetPromotionPlan:
    @pytest.mark.asyncio
    async def test_plan_built_correctly(self):
        rm = ReleaseManager()
        staging_status = {"deployments": [{"tag": "v1.5.0", "image_tags": []}]}
        prod_status = {"deployments": [{"tag": "v1.4.0", "image_tags": []}]}

        async def fake_status(service, environment=None):
            return staging_status if environment == "staging" else prod_status

        with patch.object(rm, "get_release_status", AsyncMock(side_effect=fake_status)):
            result = await rm.get_promotion_plan("checkout", "staging", "production")

        assert result["tag_to_promote"] == "v1.5.0"
        assert "deploy checkout tag v1.5.0 to production" in result["note"]

    @pytest.mark.asyncio
    async def test_no_source_tag_returns_error(self):
        rm = ReleaseManager()
        empty_status = {"deployments": []}

        with patch.object(rm, "get_release_status", AsyncMock(return_value=empty_status)):
            result = await rm.get_promotion_plan("unknown-service", "staging", "production")

        assert "error" in result
