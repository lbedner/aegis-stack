"""Retained errors in Redis: bounded atomic writes, batched indexed reads.

Records and their indexes are pruned together, by the collector each tick
and by every insert, rather than expiring one by one. Clients belong to the
caller. No SQL or worker imports.
"""

import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from app.services.system.errors import scripts
from app.services.system.errors.models import (
    MAX_PAYLOAD,
    ErrorIssue,
    ErrorOccurrence,
    ErrorSearch,
)
from app.core.key_family import KeyFamily
from app.services.system.redis_keys import decoded

InsertResult = Literal["inserted", "replay", "expired", "fenced"]
PREFIX = "aegis:errors:"
REDIS_KEYS = tuple(
    KeyFamily(pattern, kind, name, purpose, "Error tracking")
    for pattern, kind, name, purpose in (
        (
            PREFIX + "*:search",
            "hash",
            "Error search",
            "Bounded retained occurrence metadata",
        ),
        (PREFIX + "*:records", "hash", "Error occurrences", "Retained redacted errors"),
        (PREFIX + "*:all", "zset", "Error history", "Global retention index"),
        (
            PREFIX + "*:summaries",
            "hash",
            "Error summaries",
            "Retained issue counts and representatives",
        ),
        (PREFIX + "*:issues", "zset", "Error issues", "Latest occurrence order"),
        (
            PREFIX + "*:occurrences:*",
            "zset",
            "Issue history",
            "Occurrence index per issue",
        ),
        (
            PREFIX + "*:watermark",
            "string",
            "Error replay boundary",
            "Discarded-history high-water timestamp",
        ),
        (
            PREFIX + "*:lease",
            "string",
            "Error collector lease",
            "Fenced collector ownership",
        ),
        (
            PREFIX + "*:status",
            "string",
            "Error collector status",
            "Shared collection health",
        ),
        (
            PREFIX + "*:cursors",
            "hash",
            "Error source positions",
            "Bounded active-container checkpoints",
        ),
        (
            "aegis:events:errors:*",
            "stream",
            "Error notifications",
            "Capped issue-change notifications",
        ),
    )
)


class StoreUnavailableError(RuntimeError):
    """Redis is unavailable; callers display status without recursive logging."""


class ErrorStore:
    def __init__(
        self,
        client: Any,
        stack: str,
        *,
        max_occurrences: int,
        retention_seconds: int,
    ) -> None:
        self.client = client
        namespace = sha256(stack.encode()).hexdigest()[:24]
        self.prefix = f"{PREFIX}{namespace}:"
        self.notifications = f"aegis:events:errors:{namespace}"
        self.max_occurrences = max_occurrences
        self.retention_seconds = retention_seconds
        self._scripts: dict[str, Any] = {}

    def key(self, suffix: str) -> str:
        return self.prefix + suffix

    async def _guard(self, reply: Awaitable[Any]) -> Any:
        # Lazy import: minimal stacks do not install redis.
        from redis.exceptions import RedisError

        try:
            async with asyncio.timeout(3):
                return await reply
        except (RedisError, OSError, TimeoutError) as exc:
            raise StoreUnavailableError("Error history is unavailable") from exc

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        return await self._guard(getattr(self.client, method)(*args, **kwargs))

    async def run(self, script: str, keys: list[str], args: list[Any]) -> Any:
        """A script, registered once and then run by its hash (EVALSHA)."""
        if script not in self._scripts:
            self._scripts[script] = self.client.register_script(script)
        return await self._guard(self._scripts[script](keys=keys, args=args))

    def _arguments(self, now: datetime) -> list[str | int | float]:
        return [
            self.prefix,
            now.timestamp() - self.retention_seconds,
            self.max_occurrences,
        ]

    async def insert(self, event: ErrorOccurrence, *, token: str = "") -> InsertResult:
        payload = event.model_dump_json()
        if len(payload.encode()) > MAX_PAYLOAD:
            raise ValueError("Serialized error exceeds the retained payload limit")
        result = decoded(
            await self.run(
                scripts.INSERT,
                [],
                [
                    *self._arguments(datetime.now(UTC)),
                    token,
                    payload,
                    event.timestamp.timestamp(),
                    self.notifications,
                    ErrorSearch.of(event).model_dump_json(),
                ],
            )
        )
        if result not in ("inserted", "replay", "expired", "fenced"):
            raise StoreUnavailableError("Unexpected error repository result")
        return result  # type: ignore[return-value]

    async def prune(self, *, now: datetime | None = None) -> int:
        arguments = self._arguments(now or datetime.now(UTC))
        # Yield between atomic batches; no Lua invocation scans full history.
        for _ in range(80):
            count, first = await self.run(scripts.PRUNE, [], arguments)
            if int(count) <= self.max_occurrences and (
                float(first) == -1 or float(first) >= float(arguments[1])
            ):
                return int(count)
        raise StoreUnavailableError(
            "Error retention cleanup backlog exceeded its bound"
        )

    async def issues(self, *, offset: int = 0, limit: int = 50) -> list[ErrorIssue]:
        """Every retained issue, the latest first: their summaries, kept by
        each insert and prune."""
        members = await self.call(
            "zrevrange", self.key("issues"), offset, offset + limit - 1
        )
        if not members:
            return []
        rows = await self.call("hmget", self.key("summaries"), members)
        return [ErrorIssue.model_validate_json(row) for row in rows if row]

    async def issue_count(self) -> int:
        return int(await self.call("zcard", self.key("issues")))

    async def searched(self) -> list[ErrorSearch]:
        """Every retained occurrence's search projection, in one read."""
        rows = await self.call("hvals", self.key("search"))
        return [ErrorSearch.model_validate_json(row) for row in rows]

    async def detail(self, identity: str) -> ErrorOccurrence | None:
        row = await self.call("hget", self.key("records"), identity)
        return ErrorOccurrence.model_validate_json(row) if row else None

    async def occurrences(
        self, fingerprint: str, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[ErrorOccurrence], int]:
        """One issue's retained occurrences, the latest first, and how many."""
        group = self.key("occurrences:" + fingerprint)
        ids = await self.call("zrevrange", group, offset, offset + limit - 1)
        total = int(await self.call("zcard", group))
        if not ids:
            return [], total
        rows = await self.call("hmget", self.key("records"), ids)
        return [ErrorOccurrence.model_validate_json(row) for row in rows if row], total

    async def version(self) -> tuple[int, str]:
        """What changes when retention drops history quietly: the count and
        the oldest occurrence kept."""
        oldest = await self.call("zrange", self.key("all"), 0, 0)
        count = await self.call("zcard", self.key("all"))
        return int(count), decoded(oldest[0]) if oldest else ""

    async def renew(self, token: str, seconds: int) -> bool:
        return bool(
            await self.run(scripts.LEASE, [self.key("lease")], [token, seconds])
        )

    async def fenced(self, script: str, token: str, key: str, *args: Any) -> bool:
        """A collector write (``scripts.STATUS``/``CURSOR``), only while
        ``token`` holds the lease."""
        return bool(
            await self.run(script, [self.key("lease"), self.key(key)], [token, *args])
        )
