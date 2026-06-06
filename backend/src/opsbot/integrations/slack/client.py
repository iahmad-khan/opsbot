from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog
from slack_sdk.web.async_client import AsyncWebClient

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


@lru_cache
def get_slack_client() -> AsyncWebClient:
    return AsyncWebClient(token=get_settings().slack_bot_token)


class SlackClient:
    def __init__(self) -> None:
        self._client = get_slack_client()

    async def post_message(
        self,
        channel: str,
        text: str = "",
        blocks: list[dict] | None = None,
        thread_ts: str | None = None,
        mrkdwn: bool = True,
    ) -> dict:
        kwargs: dict[str, Any] = {
            "channel": channel,
            "mrkdwn": mrkdwn,
        }
        if text:
            kwargs["text"] = text
        if blocks:
            kwargs["blocks"] = blocks
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        response = await self._client.chat_postMessage(**kwargs)
        return {"ts": response["ts"], "channel": response["channel"]}

    async def update_message(
        self,
        channel: str,
        ts: str,
        text: str = "",
        blocks: list[dict] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"channel": channel, "ts": ts}
        if text:
            kwargs["text"] = text
        if blocks:
            kwargs["blocks"] = blocks
        await self._client.chat_update(**kwargs)

    async def post_ephemeral(self, channel: str, user: str, text: str, blocks: list[dict] | None = None) -> None:
        kwargs: dict[str, Any] = {"channel": channel, "user": user, "text": text}
        if blocks:
            kwargs["blocks"] = blocks
        await self._client.chat_postEphemeral(**kwargs)

    async def react(self, channel: str, ts: str, emoji: str) -> None:
        try:
            await self._client.reactions_add(channel=channel, timestamp=ts, name=emoji)
        except Exception:
            pass  # Ignore duplicate reaction errors

    async def get_user_info(self, user_id: str) -> dict:
        response = await self._client.users_info(user=user_id)
        user = response["user"]
        profile = user.get("profile", {})
        return {
            "id": user["id"],
            "name": user.get("name", ""),
            "real_name": profile.get("real_name", ""),
            "email": profile.get("email", ""),
            "display_name": profile.get("display_name", user.get("name", "")),
        }

    async def upload_snippet(self, channel: str, content: str, filename: str, title: str = "", thread_ts: str | None = None) -> None:
        kwargs: dict[str, Any] = {
            "channels": channel,
            "content": content,
            "filename": filename,
            "title": title,
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        await self._client.files_upload_v2(**kwargs)
