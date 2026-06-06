from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)


class ConversationMemory:
    """Redis-backed per-channel conversation memory."""

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis = redis_client
        s = get_settings()
        self._ttl = s.conversation_context_ttl
        self._max_messages = s.conversation_max_messages

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            s = get_settings()
            self._redis = aioredis.from_url(s.redis_url, decode_responses=True)
        return self._redis

    def _key(self, channel_id: str, thread_ts: str | None = None) -> str:
        suffix = f":{thread_ts}" if thread_ts else ""
        return f"opsbot:conv:{channel_id}{suffix}"

    async def get_history(self, channel_id: str, thread_ts: str | None = None) -> list[dict]:
        r = await self._get_redis()
        key = self._key(channel_id, thread_ts)
        raw = await r.get(key)
        if not raw:
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("memory.corrupted", key=key)
            return []

    async def append(
        self,
        channel_id: str,
        message: dict,
        thread_ts: str | None = None,
    ) -> list[dict]:
        r = await self._get_redis()
        history = await self.get_history(channel_id, thread_ts)
        history.append(message)
        # keep only the last N messages
        if len(history) > self._max_messages:
            history = history[-self._max_messages:]
        key = self._key(channel_id, thread_ts)
        await r.set(key, json.dumps(history), ex=self._ttl)
        return history

    async def append_many(
        self,
        channel_id: str,
        messages: list[dict],
        thread_ts: str | None = None,
    ) -> list[dict]:
        r = await self._get_redis()
        history = await self.get_history(channel_id, thread_ts)
        history.extend(messages)
        if len(history) > self._max_messages:
            history = history[-self._max_messages:]
        key = self._key(channel_id, thread_ts)
        await r.set(key, json.dumps(history), ex=self._ttl)
        return history

    async def clear(self, channel_id: str, thread_ts: str | None = None) -> None:
        r = await self._get_redis()
        await r.delete(self._key(channel_id, thread_ts))

    async def set_metadata(self, channel_id: str, key: str, value: Any) -> None:
        r = await self._get_redis()
        meta_key = f"opsbot:meta:{channel_id}:{key}"
        await r.set(meta_key, json.dumps(value), ex=self._ttl)

    async def get_metadata(self, channel_id: str, key: str) -> Any | None:
        r = await self._get_redis()
        meta_key = f"opsbot:meta:{channel_id}:{key}"
        raw = await r.get(meta_key)
        return json.loads(raw) if raw else None
