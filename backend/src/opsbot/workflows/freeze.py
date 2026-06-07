from __future__ import annotations

from datetime import UTC, datetime


def is_in_freeze_window() -> bool:
    """Return True if the current UTC time falls within a configured deployment freeze window.

    Configuration (via settings / env vars):
      FREEZE_DEPLOYMENT_DAYS         comma-separated ISO weekday numbers (0=Mon … 6=Sun)
      FREEZE_DEPLOYMENT_START_UTC    hour (0–23) freeze starts; -1 = all-day
      FREEZE_DEPLOYMENT_END_UTC      hour (0–23) freeze ends; supports overnight (e.g. 22→6)
    """
    from opsbot.config.settings import get_settings
    s = get_settings()

    if not s.freeze_deployment_days:
        return False

    now = datetime.now(UTC)
    if now.weekday() not in s.freeze_deployment_days:
        return False

    start = s.freeze_deployment_start_utc
    end = s.freeze_deployment_end_utc
    if start < 0:
        return True  # all-day freeze

    hour = now.hour
    if start <= end:
        return start <= hour < end
    else:
        # Overnight window, e.g. start=22, end=6 means 22:00–05:59 UTC
        return hour >= start or hour < end
