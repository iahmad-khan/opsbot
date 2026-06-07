from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from opsbot.config.settings import get_settings

log = structlog.get_logger(__name__)

# Key prefix bumped to v2 so existing string-typed keys are ignored rather than
# misread as list items.
_KEY_PREFIX = "opsbot:conv2"


class ConversationMemory:
    """
    Redis-backed per-channel conversation memory.

    Each message is stored as an individual JSON string in a Redis list so that
    appends are atomic (RPUSH) and concurrent tasks for the same channel cannot
    overwrite each other's messages (the old GET/SET blob pattern had a
    last-write-wins race).
    """

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
        return f"{_KEY_PREFIX}:{channel_id}{suffix}"

    async def get_history(self, channel_id: str, thread_ts: str | None = None) -> list[dict]:
        r = await self._get_redis()
        key = self._key(channel_id, thread_ts)
        raw_items = await r.lrange(key, 0, -1)
        history: list[dict] = []
        for item in raw_items:
            try:
                history.append(json.loads(item))
            except json.JSONDecodeError:
                log.warning("memory.item.corrupted", key=key)
        return history

    async def append(
        self,
        channel_id: str,
        message: dict,
        thread_ts: str | None = None,
    ) -> list[dict]:
        return await self.append_many(channel_id, [message], thread_ts)

    async def append_many(
        self,
        channel_id: str,
        messages: list[dict],
        thread_ts: str | None = None,
    ) -> list[dict]:
        if not messages:
            return await self.get_history(channel_id, thread_ts)
        r = await self._get_redis()
        key = self._key(channel_id, thread_ts)
        # Pipeline: push each message, trim to max_messages, refresh TTL
        async with r.pipeline(transaction=True) as pipe:
            for msg in messages:
                pipe.rpush(key, json.dumps(msg))
            pipe.ltrim(key, -self._max_messages, -1)
            pipe.expire(key, self._ttl)
            await pipe.execute()
        return await self.get_history(channel_id, thread_ts)

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
