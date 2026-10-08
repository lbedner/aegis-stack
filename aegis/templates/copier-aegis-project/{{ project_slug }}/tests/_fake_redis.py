"""An in-memory Redis for the tests that need one: the job store, the worker
load-test runs, the worker runtime reports and busy counts."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any


class FakeRedis:
    """The calls the stores make, over dicts."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.strings: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def set(self, key: str, value: str, **_options: Any) -> None:
        self.strings[key] = value

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def hset(self, key: str, mapping: dict[str, Any]) -> None:
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

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
            self.strings.pop(key, None)

    async def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)

    async def aclose(self) -> None:
        return None

    async def scan_iter(self, match: str, count: int = 100):
        for key in [*self.hashes, *self.strings]:
            if fnmatchcase(key, match):
                yield key


class _Pipeline:
    """Queued ``hgetall`` and ``get`` calls, answered in order on ``execute``."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._calls: list[tuple[str, str]] = []

    def hgetall(self, key: str) -> None:
        self._calls.append(("hgetall", key))

    def get(self, key: str) -> None:
        self._calls.append(("get", key))

    async def execute(self) -> list[Any]:
        return [await getattr(self._redis, op)(key) for op, key in self._calls]
