"""Key-value store for caching Library of Congress responses and counting requests.

Uses Upstash Redis when its credentials are set, so every serverless instance
shares one cache and one rate-limit counter. Falls back to an in-process store
otherwise (local runs, or a deploy without Redis).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol

logger = logging.getLogger(__name__)

PREFIX = "tmn:"


class Store(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl: int) -> None: ...

    async def incr(self, key: str, ttl: int) -> int:
        """Increment a counter, starting its TTL on first use, and return the new value."""
        ...


class MemoryStore:
    def __init__(self, max_entries: int = 500):
        self._data: dict[str, tuple[float, str]] = {}
        self._max_entries = max_entries

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.time():
            del self._data[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data.pop(key, None)
        self._data[key] = (time.time() + ttl, value)
        while len(self._data) > self._max_entries:
            del self._data[next(iter(self._data))]

    async def incr(self, key: str, ttl: int) -> int:
        current = await self.get(key)
        if current is None:
            self._data[key] = (time.time() + ttl, "1")
            return 1
        expires, _ = self._data[key]
        value = int(current) + 1
        self._data[key] = (expires, str(value))
        return value


class RedisStore:
    """Upstash Redis over its REST API. Errors are logged and treated as a cache miss
    so a Redis outage degrades to uncached requests instead of failing tools."""

    def __init__(self, url: str, token: str):
        from upstash_redis.asyncio import Redis

        self._redis = Redis(url=url, token=token, rest_retries=0, allow_telemetry=False)

    async def get(self, key: str) -> str | None:
        try:
            return await self._redis.get(key)
        except Exception:
            logger.warning("Redis get failed", exc_info=True)
            return None

    async def set(self, key: str, value: str, ttl: int) -> None:
        try:
            await self._redis.set(key, value, ex=ttl)
        except Exception:
            logger.warning("Redis set failed", exc_info=True)

    async def incr(self, key: str, ttl: int) -> int:
        try:
            value = await self._redis.incr(key)
            if value == 1:
                await self._redis.expire(key, ttl)
            return value
        except Exception:
            logger.warning("Redis incr failed", exc_info=True)
            return 0


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        # The Vercel Marketplace Upstash integration sets the KV_* names.
        url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
        token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
        _store = RedisStore(url, token) if url and token else MemoryStore()
    return _store
