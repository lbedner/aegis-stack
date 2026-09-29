"""Every WebSocket and event stream, open now and recently closed.

The Overseer's Server > Connections section reads ``history()``. Nothing
else lists them: uvicorn keeps its own set but the app cannot reach it,
and each stream's subscriber set only knows itself. A WebSocket is
listed once accepted; an HTTP response once it starts as
``text/event-stream``. A client that comes back (same kind, path, address
and browser) within ``GRACE_SECONDS`` of dropping is the same connection
reconnecting, so a Flet tab riding out a hot reload is one row with a
timeline, not a new row each time.

Each record names the server process that owns it, and each process
renews a short heartbeat. A record left "up" by a process that died
without closing it (a hot reload that timed out) reads as closed ("server
went away"), and the client coming back links to it as a reconnect.

Each connection's record lives in the shared cache (``app.core.cache``):
Redis when the project has it, so history outlives a restart and covers
every worker, and process memory otherwise. Records are written on open
and close only; message counts while open stay in this process. A cache
failure is logged and never reaches the connection. The query string is
never kept (it can carry a token).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha1
from itertools import count
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.cache import get_cache
from app.core.log import logger

try:  # Redis is optional; its errors are not OSErrors
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - a project without redis
    RedisError = ConnectionError  # type: ignore[assignment,misc]

_CACHE_ERRORS = (ConnectionError, OSError, TimeoutError, RedisError)

GRACE_SECONDS = 30
RECORD_TTL = 24 * 3600
MAX_EVENTS = 50
RECORD = "connections:record:"
RECENT = "connections:recent:"
ALIVE = "connections:alive:"
HEARTBEAT_SECONDS = 10
ALIVE_TTL = 30
# This process: the owner stamped on every record it writes.
BOOT = uuid4().hex[:8]


@dataclass
class Connection:
    """One socket open in this process right now."""

    kind: str  # "websocket" or "sse"
    path: str
    client: str | None
    agent: str | None
    opened_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sent: int = 0
    received: int = 0
    record_id: str | None = None


_OPEN: dict[int, Connection] = {}
_ids = count()


def open_connections() -> list[Connection]:
    """The sockets open in this process, longest-lived first."""
    return sorted(_OPEN.values(), key=lambda c: c.opened_at)


def _connection(scope: Scope, kind: str) -> Connection:
    client = scope.get("client")
    headers = dict(scope.get("headers") or [])
    agent = headers.get(b"user-agent")
    return Connection(
        kind=kind,
        path=scope.get("path", ""),
        client=client[0] if client else None,
        agent=agent.decode("latin-1") if agent else None,
    )


def _identity(conn: Connection) -> str:
    """Who is connecting to what: the key a returning client matches."""
    raw = f"{conn.kind}|{conn.path}|{conn.client}|{conn.agent}"
    return sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def _event(record: dict[str, Any], what: str, detail: str | None = None) -> None:
    record["events"] = [*record["events"], (datetime.now(UTC), what, detail)][
        -MAX_EVENTS:
    ]


async def _record_open(conn: Connection) -> None:
    cache = get_cache()
    identity = _identity(conn)
    returning = await cache.get(RECENT + identity)
    record = await cache.get(RECORD + returning) if returning else None
    now = datetime.now(UTC)
    if record is not None:
        await cache.invalidate(RECENT + identity)
        gap = int((now - record["closed_at"]).total_seconds())
        _reopen(record, now)
        _event(record, "reconnected", f"after {gap}s")
    elif (record := await _orphan(identity)) is not None:
        _event(record, "dropped", "server went away")
        _reopen(record, now)
        _event(record, "reconnected", "after a server restart")
    else:
        record = {
            "id": uuid4().hex[:12],
            "kind": conn.kind,
            "path": conn.path,
            "client": conn.client,
            "agent": conn.agent,
            "first_opened": now,
            "opened_at": now,
            "closed_at": None,
            "state": "up",
            "ended": None,
            "reconnects": 0,
            "sent": 0,
            "received": 0,
            "events": [],
        }
        _event(record, "connected")
    record["owner"] = BOOT
    record["identity"] = identity
    conn.record_id = record["id"]
    await cache.set(RECORD + record["id"], record, ttl=RECORD_TTL)


def _reopen(record: dict[str, Any], now: datetime) -> None:
    record.update(state="up", opened_at=now, closed_at=None, ended=None)
    record["reconnects"] += 1


async def _orphan(identity: str) -> dict[str, Any] | None:
    """This client's record left "up" by a server process that has died."""
    alive = await _alive_owners()
    records = await get_cache().values_with_prefix(RECORD)
    return next(
        (
            r
            for r in records.values()
            if r.get("identity") == identity
            and r["state"] == "up"
            and r.get("owner") not in alive
        ),
        None,
    )


async def _alive_owners() -> set[str]:
    """This process, and every other one whose heartbeat is current."""
    beats = await get_cache().values_with_prefix(ALIVE)
    return {BOOT} | {key.removeprefix(ALIVE) for key in beats}


async def heartbeat() -> None:
    await get_cache().set(ALIVE + BOOT, True, ttl=ALIVE_TTL)


async def keep_alive() -> None:
    """Renew this process's heartbeat until cancelled (the startup hook)."""
    while True:
        await _safely("heartbeat", heartbeat())
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def _record_close(conn: Connection, ended: str) -> None:
    cache = get_cache()
    record = await cache.get(RECORD + (conn.record_id or ""))
    if record is None:
        return
    record.update(state="down", closed_at=datetime.now(UTC), ended=ended)
    record["sent"] += conn.sent
    record["received"] += conn.received
    _event(record, "dropped", ended)
    await cache.set(RECORD + record["id"], record, ttl=RECORD_TTL)
    await cache.set(RECENT + _identity(conn), record["id"], ttl=GRACE_SECONDS)


async def _safely(step: str, work: Any) -> None:
    """Run a record write; a cache that is down costs the history, never
    the connection."""
    try:
        await work
    except _CACHE_ERRORS as exc:
        logger.warning("connections.record_failed", step=step, error=str(exc))


def _state(record: dict[str, Any], now: datetime, alive: set[str]) -> str:
    if record["state"] == "up":
        return "up" if record.get("owner") in alive else "closed"
    since = (now - record["closed_at"]).total_seconds()
    return "reconnecting" if since < GRACE_SECONDS else "closed"


async def history() -> list[dict[str, Any]]:
    """Every remembered connection, open first then most recently closed,
    with this process's live counts added to the ones open here."""
    records = await get_cache().values_with_prefix(RECORD)
    by_id = {r["id"]: dict(r) for r in records.values()}
    for conn in _OPEN.values():
        record = by_id.get(conn.record_id or "")
        if record is not None:
            record["sent"] += conn.sent
            record["received"] += conn.received
    now = datetime.now(UTC)
    alive = await _alive_owners()
    for record in by_id.values():
        if record["state"] == "up" and record.get("owner") not in alive:
            record["ended"] = "server went away"
        record["state"] = _state(record, now, alive)
    return sorted(
        by_id.values(),
        key=lambda r: (r["state"] != "up", -(r["closed_at"] or now).timestamp()),
    )


async def find(record_id: str) -> dict[str, Any] | None:
    """One remembered connection, as ``history()`` shows it."""
    return next((r for r in await history() if r["id"] == record_id), None)


class ConnectionsMiddleware:
    """Pure ASGI: sees the messages, never buffers them."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        key = next(_ids)
        kind = "websocket" if scope["type"] == "websocket" else "sse"
        ended = "server finished"

        async def counted_receive() -> Message:
            nonlocal ended
            message = await receive()
            if message["type"] in ("websocket.disconnect", "http.disconnect"):
                ended = "client went away"
            elif message["type"] == "websocket.receive" and key in _OPEN:
                _OPEN[key].received += 1
            return message

        async def watched_send(message: Message) -> None:
            nonlocal ended
            kind_of = message["type"]
            opens = kind_of == "websocket.accept" or (
                kind_of == "http.response.start"
                and b"text/event-stream"
                in dict(message.get("headers") or []).get(b"content-type", b"")
            )
            if opens:
                _OPEN[key] = _connection(scope, kind)
                await _safely("open", _record_open(_OPEN[key]))
            elif kind_of == "websocket.close":
                ended = "closed by server"
            elif key in _OPEN and (
                kind_of in ("websocket.send", "http.response.pathsend")
                or (kind_of == "http.response.body" and message.get("body"))
            ):
                _OPEN[key].sent += 1
            # Every message, a granian ``http.response.pathsend`` file
            # included, goes on exactly as it came: this only counts.
            await send(message)

        try:
            await self.app(scope, counted_receive, watched_send)
        except Exception as exc:
            ended = f"error: {type(exc).__name__}"
            raise
        finally:
            conn = _OPEN.pop(key, None)
            if conn is not None:
                await _safely("close", _record_close(conn, ended))


def register_middleware(app: FastAPI) -> None:
    app.add_middleware(ConnectionsMiddleware)
