from __future__ import annotations

from fastapi import APIRouter, Request, Response
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler

from opsbot.integrations.slack.handlers import get_bolt_app

router = APIRouter(prefix="/slack", tags=["slack"])

_handler: AsyncSlackRequestHandler | None = None


def _get_handler() -> AsyncSlackRequestHandler:
    global _handler
    if _handler is None:
        _handler = AsyncSlackRequestHandler(get_bolt_app())
    return _handler


@router.post("/events")
async def slack_events(req: Request) -> Response:
    return await _get_handler().handle(req)


@router.post("/interactive")
async def slack_interactive(req: Request) -> Response:
    return await _get_handler().handle(req)


@router.get("/oauth/callback")
async def slack_oauth_callback(req: Request) -> Response:
    return await _get_handler().handle(req)
