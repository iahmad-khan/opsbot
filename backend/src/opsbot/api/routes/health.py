from __future__ import annotations

import time

from fastapi import APIRouter
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from opsbot.config.settings import get_settings
from opsbot.mcp.manager import get_manager
from opsbot.models.schemas import HealthResponse

router = APIRouter(tags=["health"])

_start_time = time.time()
VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    s = get_settings()
    manager = get_manager()
    checks: dict[str, str] = {"api": "ok"}
    overall_ok = True

    # Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(s.redis_url)
        await r.ping()
        checks["redis"] = "ok"
        await r.aclose()
    except Exception as e:
        checks["redis"] = f"error: {e}"
        overall_ok = False

    # PostgreSQL
    try:
        from sqlalchemy import text

        from opsbot.models.db import make_engine
        engine = make_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
        await engine.dispose()
    except Exception as e:
        checks["database"] = f"error: {e}"
        overall_ok = False

    # LLM provider key present
    llm_key_present = bool(
        s.anthropic_api_key or s.openai_api_key or s.google_api_key
    )
    checks["llm_configured"] = "ok" if llm_key_present else "warning: no LLM API key set"
    if not llm_key_present:
        overall_ok = False

    # Slack tokens present
    slack_ready = bool(s.slack_bot_token and s.slack_signing_secret)
    checks["slack_configured"] = "ok" if slack_ready else "warning: SLACK_BOT_TOKEN or SLACK_SIGNING_SECRET not set"

    # MCP servers
    mcp_servers = manager.get_server_status()
    failed_mcp = [name for name, status in mcp_servers.items() if status != "connected"]
    if failed_mcp:
        checks["mcp_servers"] = f"degraded: {', '.join(failed_mcp)} not connected"
        # MCP degraded is a warning, not a fatal failure — some servers are optional
    else:
        checks["mcp_servers"] = "ok"

    return HealthResponse(
        status="ok" if overall_ok else "degraded",
        version=VERSION,
        environment=s.app_env,
        checks=checks,
        mcp_servers=mcp_servers,
    )


@router.get("/ready")
async def ready() -> dict:
    """Kubernetes readiness probe — only passes when critical deps are up."""
    s = get_settings()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(s.redis_url)
        await r.ping()
        await r.aclose()
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"ready": False, "reason": f"redis: {e}"})

    try:
        from sqlalchemy import text

        from opsbot.models.db import make_engine
        engine = make_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={"ready": False, "reason": f"database: {e}"})

    return {"ready": True}


@router.get("/alive")
async def alive() -> dict:
    return {"alive": True, "uptime_seconds": int(time.time() - _start_time)}


@router.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
