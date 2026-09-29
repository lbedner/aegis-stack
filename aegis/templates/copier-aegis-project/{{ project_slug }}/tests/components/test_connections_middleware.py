"""Every WebSocket and event stream, for the Overseer's Server >
Connections section: listed while open, counted while it talks, and
remembered after with a timeline. A client that comes back within the
grace window is the same connection reconnecting, not a new one. Plain
requests are never listed."""

from typing import Any

import pytest

from app.components.backend.middleware import connections
from app.components.backend.middleware.connections import (
    ConnectionsMiddleware,
    history,
    open_connections,
)
from app.core.cache import CacheService


@pytest.fixture(autouse=True)
def cache(monkeypatch: pytest.MonkeyPatch) -> CacheService:
    """A private in-memory cache per test."""
    fresh = CacheService()
    monkeypatch.setattr(connections, "get_cache", lambda: fresh)
    return fresh


async def _drive(
    app: Any, scope: dict[str, Any], incoming: list[dict[str, Any]]
) -> None:
    queue = list(incoming)

    async def receive() -> dict[str, Any]:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        return None

    await ConnectionsMiddleware(app)(scope, receive, send)


def _http(path: str) -> dict[str, Any]:
    return {
        "type": "http",
        "path": path,
        "query_string": b"token=secret",
        "client": ("10.0.0.5", 51000),
        "headers": [(b"user-agent", b"Firefox")],
    }


async def test_an_event_stream_is_listed_while_it_is_open() -> None:
    seen: list[list[Any]] = []

    async def stream(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream; charset=utf-8")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True}
        )
        seen.append(open_connections())
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    await _drive(stream, _http("/overseer/events"), [])
    [live] = seen[0]
    assert (live.kind, live.path, live.client) == (
        "sse",
        "/overseer/events",
        "10.0.0.5",
    )
    assert live.sent == 1 and "secret" not in repr(live)
    assert open_connections() == []


async def test_a_plain_response_is_never_listed() -> None:
    seen: list[list[Any]] = []

    async def page(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            }
        )
        seen.append(open_connections())
        await send({"type": "http.response.body", "body": b"<p>hi</p>"})

    await _drive(page, _http("/"), [])
    assert seen == [[]]


async def test_a_websocket_is_listed_from_accept_to_close() -> None:
    seen: list[list[Any]] = []

    async def socket(scope: Any, receive: Any, send: Any) -> None:
        await receive()  # websocket.connect
        await send({"type": "websocket.accept"})
        await receive()  # one message in
        await send({"type": "websocket.send", "text": "hello"})
        seen.append(open_connections())
        await send({"type": "websocket.close"})

    scope = {
        "type": "websocket",
        "path": "/dashboard/ws",
        "client": ("127.0.0.1", 1),
        "headers": [],
    }
    await _drive(
        socket,
        scope,
        [{"type": "websocket.connect"}, {"type": "websocket.receive", "text": "hi"}],
    )
    [live] = seen[0]
    assert (live.kind, live.path, live.sent, live.received) == (
        "websocket",
        "/dashboard/ws",
        1,
        1,
    )
    assert open_connections() == []


async def test_a_failing_app_still_leaves_the_list() -> None:
    async def broken(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        raise RuntimeError("stream died")

    try:
        await _drive(broken, _http("/api/v1/jobs/events"), [])
    except RuntimeError:
        pass
    assert open_connections() == []


async def _sse(path: str = "/overseer/events", fail: bool = False) -> None:
    async def stream(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True}
        )
        if fail:
            raise RuntimeError("boom")
        await receive()  # the client goes away

    try:
        await _drive(stream, _http(path), [{"type": "http.disconnect"}])
    except RuntimeError:
        pass


async def test_a_closed_connection_is_remembered_with_how_it_ended() -> None:
    await _sse()
    [record] = await history()
    assert record["state"] == "reconnecting"  # inside the grace window
    assert record["ended"] == "client went away" and record["sent"] == 1
    assert [what for _, what, _ in record["events"]] == ["connected", "dropped"]


async def test_coming_back_inside_the_grace_window_is_the_same_connection() -> None:
    await _sse()
    await _sse()
    [record] = await history()
    assert record["reconnects"] == 1 and record["sent"] == 2
    assert [what for _, what, _ in record["events"]] == [
        "connected",
        "dropped",
        "reconnected",
        "dropped",
    ]


async def test_after_the_grace_window_it_is_closed_and_a_return_is_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connections, "GRACE_SECONDS", 0)
    await _sse()
    await _sse()
    records = await history()
    assert len(records) == 2 and {r["state"] for r in records} == {"closed"}


async def test_a_crash_is_recorded_as_an_error() -> None:
    await _sse(fail=True)
    [record] = await history()
    assert record["ended"] == "error: RuntimeError"


async def test_an_open_connection_reads_up_with_live_counts() -> None:
    seen: list[list[dict[str, Any]]] = []

    async def stream(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True}
        )
        await send(
            {"type": "http.response.body", "body": b"data: 2\n\n", "more_body": True}
        )
        seen.append(await history())
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    await _drive(stream, _http("/overseer/events"), [])
    [record] = seen[0]
    assert record["state"] == "up" and record["sent"] == 2


async def test_a_cache_failure_never_breaks_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Down(CacheService):
        async def get(self, key: str) -> Any:
            raise ConnectionError("redis is down")

        async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(connections, "get_cache", lambda: Down())
    await _sse()  # no exception reaches the app or the client
    assert open_connections() == []


async def test_a_file_response_passes_through_untouched() -> None:
    """Granian sends a file as ``http.response.pathsend``; it goes on as is."""
    sent: list[dict[str, Any]] = []
    start = {"type": "http.response.start", "status": 200, "headers": []}
    pathsend = {"type": "http.response.pathsend", "path": "/static/app.js"}

    async def files(scope: Any, receive: Any, send: Any) -> None:
        await send(start)
        await send(pathsend)

    async def record(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    await ConnectionsMiddleware(files)(_http("/static/app.js"), receive, record)
    assert sent == [start, pathsend]


def _ghost(
    identity_of: str = "/overseer/events", owner: str | None = "gone"
) -> dict[str, Any]:
    """A record left "up" by a server process that died without closing it."""
    from datetime import UTC, datetime, timedelta

    conn = connections._connection(_http(identity_of), "sse")
    then = datetime.now(UTC) - timedelta(minutes=10)
    record = {
        "id": "ghost1",
        "kind": "sse",
        "path": identity_of,
        "client": conn.client,
        "agent": conn.agent,
        "first_opened": then,
        "opened_at": then,
        "closed_at": None,
        "state": "up",
        "ended": None,
        "reconnects": 0,
        "sent": 0,
        "received": 0,
        "events": [(then, "connected", None)],
        "identity": connections._identity(conn),
    }
    if owner is not None:
        record["owner"] = owner
    return record


async def test_an_up_record_whose_server_died_reads_closed(cache: CacheService) -> None:
    await cache.set(connections.RECORD + "ghost1", _ghost(), ttl=60)
    [record] = await history()
    assert record["state"] == "closed" and record["ended"] == "server went away"


async def test_a_record_from_before_owners_is_a_ghost_too(cache: CacheService) -> None:
    await cache.set(connections.RECORD + "ghost1", _ghost(owner=None), ttl=60)
    [record] = await history()
    assert record["state"] == "closed"


async def test_a_live_process_keeps_its_records_up(cache: CacheService) -> None:
    await cache.set(connections.RECORD + "ghost1", _ghost(owner="elsewhere"), ttl=60)
    await cache.set(connections.ALIVE + "elsewhere", True, ttl=60)
    [record] = await history()
    assert record["state"] == "up"


async def test_returning_after_a_server_restart_is_the_same_connection(
    cache: CacheService,
) -> None:
    await cache.set(connections.RECORD + "ghost1", _ghost(), ttl=60)
    await _sse()
    [record] = await history()
    assert record["id"] == "ghost1" and record["reconnects"] == 1
    assert [(w, d) for _, w, d in record["events"][1:3]] == [
        ("dropped", "server went away"),
        ("reconnected", "after a server restart"),
    ]


async def test_the_heartbeat_marks_this_process_alive(cache: CacheService) -> None:
    await connections.heartbeat()
    assert await cache.get(connections.ALIVE + connections.BOOT) is True
