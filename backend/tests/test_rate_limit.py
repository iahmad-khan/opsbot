"""Tests for the Slack rate limiter."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_under_limit_returns_true(self):
        """First request should be allowed."""
        from opsbot.integrations.slack.handlers import _check_rate_limit

        mock_results = [None, None, 1, None]  # zadd, zremrange, zcard=1, expire

        mock_pipe = MagicMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_pipe.execute = AsyncMock(return_value=mock_results)

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)  # pipeline() is sync
        mock_redis.aclose = AsyncMock()

        with patch("opsbot.integrations.slack.handlers.get_settings") as mock_settings, \
             patch("redis.asyncio.from_url", return_value=mock_redis):
            mock_settings.return_value.redis_url = "redis://localhost"
            result = await _check_rate_limit("U_test")

        assert result is True

    @pytest.mark.asyncio
    async def test_over_limit_returns_false(self):
        """Exceeding rate limit should be rejected."""
        from opsbot.integrations.slack.handlers import _check_rate_limit, _RATE_LIMIT_MAX

        mock_results = [None, None, _RATE_LIMIT_MAX + 1, None]  # over limit

        mock_pipe = MagicMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_pipe.execute = AsyncMock(return_value=mock_results)

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)  # pipeline() is sync
        mock_redis.aclose = AsyncMock()

        with patch("opsbot.integrations.slack.handlers.get_settings") as mock_settings, \
             patch("redis.asyncio.from_url", return_value=mock_redis):
            mock_settings.return_value.redis_url = "redis://localhost"
            result = await _check_rate_limit("U_spammer")

        assert result is False

    @pytest.mark.asyncio
    async def test_redis_failure_fails_open(self):
        """If Redis is unavailable, rate limiting fails open (allows request)."""
        from opsbot.integrations.slack.handlers import _check_rate_limit

        with patch("redis.asyncio.from_url", side_effect=Exception("Redis down")), \
             patch("opsbot.integrations.slack.handlers.get_settings") as mock_settings:
            mock_settings.return_value.redis_url = "redis://localhost"
            result = await _check_rate_limit("U_any")

        assert result is True  # fail open
