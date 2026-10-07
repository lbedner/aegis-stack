"""An in-memory Redis for the job store (``RedisJobStore``)."""

from __future__ import annotations


class FakeRedis:
    """The calls the store makes, over a dict."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttl: dict[str, int] = {}

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self.hashes.setdefault(key, {}).update(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    async def aclose(self) -> None:
        return None

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.hashes):
            if key.startswith(prefix):
                yield key
