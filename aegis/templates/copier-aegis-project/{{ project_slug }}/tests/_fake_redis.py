"""An in-memory Redis for the job store (``RedisJobStore``) and the worker
load-test runs."""

from __future__ import annotations

from typing import Any


class FakeRedis:
    """The calls the stores make, over dicts."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.ttl: dict[str, int] = {}

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes.setdefault(key, {}).update(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def rpush(self, key: str, *values: str) -> None:
        self.lists.setdefault(key, []).extend(values)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start : end + 1]

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrevrange(self, key: str, start: int, end: int) -> list[str]:
        members = sorted(self.zsets.get(key, {}).items(), key=lambda m: -m[1])
        return [m for m, _ in members][start : end + 1]

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.hashes.pop(key, None)
            self.lists.pop(key, None)

    async def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)

    async def aclose(self) -> None:
        return None

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.hashes):
            if key.startswith(prefix):
                yield key


class _Pipeline:
    """Queued ``hgetall`` calls, answered in order on ``execute``."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._keys: list[str] = []

    def hgetall(self, key: str) -> None:
        self._keys.append(key)

    async def execute(self) -> list[Any]:
        return [await self._redis.hgetall(k) for k in self._keys]
