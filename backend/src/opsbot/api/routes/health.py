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

    checks = {
        "api": "ok",
    }
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(s.redis_url)
        await r.ping()
        checks["redis"] = "ok"
        await r.aclose()
    except Exception as e:
        checks["redis"] = f"error: {e}"

    return HealthResponse(
        status="ok",
        version=VERSION,
        environment=s.app_env,
        checks=checks,
        mcp_servers=manager.get_server_status(),
    )


@router.get("/ready")
async def ready() -> dict:
    return {"ready": True}


@router.get("/alive")
async def alive() -> dict:
    return {"alive": True, "uptime_seconds": int(time.time() - _start_time)}


@router.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
