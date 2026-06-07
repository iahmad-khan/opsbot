from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from opsbot.api.routes import approvals, health, slack, sre, tasks
from opsbot.config.settings import get_settings
from opsbot.mcp.manager import get_manager

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    log.info("opsbot.startup", env=s.app_env, model=s.litellm_default_model)

    # Initialize MCP servers
    manager = get_manager()
    try:
        await manager.initialize()
        log.info("mcp.initialized", servers=list(manager.get_server_status().keys()))
    except Exception as e:
        log.error("mcp.init.failed", error=str(e))

    # Start Slack socket mode in background (only when tokens are configured)
    slack_task = None
    if s.slack_app_token and s.slack_bot_token:
        from opsbot.integrations.slack.handlers import start_socket_mode
        slack_task = asyncio.create_task(start_socket_mode())
        log.info("slack.socket_mode.starting")

    yield

    # Cleanup
    if slack_task:
        slack_task.cancel()
        import contextlib
        with contextlib.suppress(asyncio.CancelledError):
            await slack_task

    await manager.shutdown()
    log.info("opsbot.shutdown")


def create_app() -> FastAPI:
    s = get_settings()

    app = FastAPI(
        title="OpsBot API",
        description="Advanced DevOps & SRE Automation Platform",
        version="0.1.0",
        docs_url="/docs" if not s.is_production else None,
        redoc_url="/redoc" if not s.is_production else None,
        openapi_url="/openapi.json" if not s.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Correlation ID middleware — stamps every request with a trace ID
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        structlog.contextvars.unbind_contextvars("request_id")
        return response

    # Register routers
    app.include_router(health.router)
    app.include_router(slack.router)
    app.include_router(tasks.router)
    app.include_router(approvals.router)
    app.include_router(sre.router)

    return app


app = create_app()
