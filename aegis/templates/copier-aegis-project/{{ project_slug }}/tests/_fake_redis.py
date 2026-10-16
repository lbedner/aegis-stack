"""An in-memory Redis for the tests that need one: the job store, the worker
load-test runs, the worker runtime reports and busy counts, and what a key
family holds (``redis_facts``)."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any


class ReplyError(Exception):
    """An error Redis answers with: WRONGTYPE, a command with no keys."""


class FakeRedis:
    """The calls the stores make, over dicts. A stream is its entries
    (``(id, fields)``, oldest first), with ``added`` (every entry it was
    ever given) and ``groups`` (``XINFO GROUPS``) beside it."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.strings: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.sets: dict[str, set[str]] = {}
        self.added: dict[str, int] = {}
        self.groups: dict[str, list[dict[str, Any]]] = {}
        self.ttl: dict[str, int] = {}

    def _stores(self) -> dict[str, dict[str, Any]]:
        return {
            "hash": self.hashes,
            "list": self.lists,
            "zset": self.zsets,
            "string": self.strings,
            "stream": self.streams,
            "set": self.sets,
        }

    def _of(self, kind: str, key: str) -> Any:
        """``key``'s value if it is a ``kind``, empty if absent; another
        type's key is Redis's WRONGTYPE."""
        if self._type(key) not in (kind, "none"):
            raise ReplyError(f"WRONGTYPE {key} is not a {kind}")
        return self._stores()[kind].get(key, [] if kind in ("list", "stream") else {})

    def _type(self, key: str) -> str:
        return next((t for t, store in self._stores().items() if key in store), "none")

    async def type(self, key: str) -> str:
        return self._type(key)

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

    async def zrevrange(
        self, key: str, start: int, end: int, withscores: bool = False
    ) -> list[Any]:
        members = sorted(self._of("zset", key).items(), key=lambda m: -m[1])
        picked = members[start : end + 1]
        return picked if withscores else [m for m, _ in picked]

    async def zrange(
        self, key: str, start: int, end: int, withscores: bool = False
    ) -> list[Any]:
        members = sorted(self._of("zset", key).items(), key=lambda m: m[1])
        picked = members[start:] if end == -1 else members[start : end + 1]
        return picked if withscores else [m for m, _ in picked]

    async def zcard(self, key: str) -> int:
        return len(self._of("zset", key))

    async def zcount(self, key: str, low: float, high: float | str) -> int:
        """``high`` as Redis takes it: ``(x`` excludes ``x``."""
        top = str(high)
        below = float(top[1:]) if top.startswith("(") else None
        return sum(
            1
            for score in self._of("zset", key).values()
            if score >= low
            and (score < below if below is not None else score <= float(top))
        )

    async def xinfo_stream(self, key: str) -> dict[str, Any]:
        entries = self._of("stream", key)
        return {
            "length": len(entries),
            "entries-added": self.added.get(key, len(entries)),
            "first-entry": entries[0] if entries else None,
            "last-entry": entries[-1] if entries else None,
        }

    async def xinfo_groups(self, key: str) -> list[dict[str, Any]]:
        self._of("stream", key)
        return self.groups.get(key, [])

    async def xrevrange(
        self, key: str, max: str = "+", min: str = "-", count: int | None = None
    ) -> list[Any]:
        floor = 0 if min == "-" else int(min.split("-")[0])
        newest = [
            e
            for e in reversed(self._of("stream", key))
            if int(e[0].split("-")[0]) >= floor
        ]
        return newest[:count] if count else newest

    async def xlen(self, key: str) -> int:
        return len(self._of("stream", key))

    async def ltrim(self, key: str, start: int, end: int) -> None:
        items = self.lists.get(key, [])
        self.lists[key] = items[start:] if end == -1 else items[start : end + 1]

    async def sadd(self, key: str, *members: str) -> None:
        self.sets.setdefault(key, set()).update(members)

    async def smembers(self, key: str) -> list[str]:
        return sorted(self.sets.get(key, ()))

    async def srem(self, key: str, *members: str) -> None:
        self.sets.get(key, set()).difference_update(members)

    async def exists(self, key: str) -> int:
        return int(self._type(key) != "none")

    async def command_getkeys(self, *command: str) -> list[str]:
        """``COMMAND GETKEYS``, for one-key commands: the first argument."""
        if len(command) < 2:
            raise ReplyError("The command has no key arguments")
        return [command[1]]

    async def strlen(self, key: str) -> int:
        return len(self._of("string", key) or "")

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.strings.get(k) for k in keys]

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
        for key in [*self.hashes, *self.strings, *self.zsets, *self.streams]:
            if fnmatchcase(key, match):
                yield key


class _Pipeline:
    """Any ``FakeRedis`` call, queued and answered in order on ``execute``;
    with ``raise_on_error=False`` an error reply is its answer, as
    redis-py gives it."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def queued(*args: Any, **kwargs: Any) -> None:
            self._calls.append((name, args, kwargs))

        return queued

    async def execute(self, raise_on_error: bool = True) -> list[Any]:
        found: list[Any] = []
        for name, args, kwargs in self._calls:
            try:
                found.append(await getattr(self._redis, name)(*args, **kwargs))
            except ReplyError as exc:
                if raise_on_error:
                    raise
                found.append(exc)
        return found
