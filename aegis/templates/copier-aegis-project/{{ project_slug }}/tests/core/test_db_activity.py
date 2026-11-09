"""Database activity (``app.core.db_activity``): a transaction held past
``DATABASE_SLOW_TRANSACTION_SECONDS``, and a write that found the database
locked, are recorded with the process and the app code behind them, for the
Database pages. Against a real SQLite file: the lock is SQLite's own."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
import socket
import sqlite3
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import db_activity
from app.core.cache import get_cache
from app.core.config import settings
from app.core.source_index import ROOT
from app.services.system.models import ComponentStatus
from tests._db_activity import event as _event
from tests._db_activity import kept as _kept


@pytest.fixture(autouse=True)
async def clean(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setitem(settings.__dict__, "DATABASE_SLOW_TRANSACTION_SECONDS", 0.05)
    monkeypatch.setattr(db_activity, "SHOWN_AFTER", 0.05)
    monkeypatch.setattr(db_activity, "SWEEP", 0.05)
    await _forget()
    yield
    await _forget()


async def _forget() -> None:
    await get_cache().invalidate(db_activity.KEY)
    await get_cache().invalidate_prefix(db_activity.HELD)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "app.db"


@pytest.fixture
def engine(path: Path) -> Iterator[Engine]:
    watched = create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.05})
    db_activity.watch(watched)
    yield watched
    watched.dispose()


async def _recorded() -> list[dict]:
    await asyncio.sleep(0)  # records are written on the loop
    return await db_activity.recent(3600)


async def test_a_transaction_held_too_long_names_its_caller(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
        time.sleep(0.1)
    (event,) = await _recorded()
    assert event["kind"] == "slow" and event["seconds"] >= 0.1
    assert "test_a_transaction_held_too_long_names_its_caller" in event["caller"]
    assert event["process"] and event["host"] == db_activity.HOST


def test_a_record_names_who_owns_its_code() -> None:
    """Owned as a log line is, when it is recorded, so the Services picker
    Logs and Errors share narrows it the same way."""
    found = _event("app/services/payment/health.py:38 in check")
    assert (found["app_service"], found["app_component"]) == ("payment", None)


async def test_an_async_session_names_its_caller(path: Path) -> None:
    """Async sessions run in a greenlet, apart from the coroutine that asked:
    the caller is found along the task's chain of awaits."""
    pytest.importorskip("aiosqlite")  # a Postgres stack has no SQLite driver
    watched = create_async_engine(f"sqlite+aiosqlite:///{path}")
    db_activity.watch(watched.sync_engine)
    try:
        async with watched.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await asyncio.sleep(0.1)
    finally:
        await watched.dispose()
    (event,) = await _recorded()
    assert "test_an_async_session_names_its_caller" in event["caller"]


async def test_a_cancelled_statement_ends_as_a_cancel(path: Path) -> None:
    """Ctrl+C (or a client gone) cancels a statement mid-flight, which leaves
    its connection invalid; the rollback that cleans it up runs these
    listeners, and one that reads the connection's ``info`` there raised
    "Can't reconnect until invalid transaction is rolled back" in place of
    the cancel (``ai chat`` printed it as its error)."""
    pytest.importorskip("aiosqlite")
    watched = create_async_engine(f"sqlite+aiosqlite:///{path}")
    db_activity.watch(watched.sync_engine)
    slow = text(
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c"
        " WHERE x < 3000000) SELECT count(*) FROM c"
    )

    sent = asyncio.Event()

    @event.listens_for(watched.sync_engine, "before_cursor_execute")
    def _sending(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        if "RECURSIVE" in statement:
            sent.set()

    async def query() -> None:
        async with watched.begin() as conn:
            await conn.execute(slow)

    try:
        running = asyncio.create_task(query())
        # Set just before the driver call, so the task is now waiting on
        # the statement: cancelled there however fast the machine.
        await sent.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    finally:
        await watched.dispose()


async def test_a_transaction_is_seen_while_it_is_held(path: Path) -> None:
    """Held, across every process: who, which code, from when, and the
    container to restart; gone once it ends. SQLite names no holder itself."""
    pytest.importorskip("aiosqlite")
    watched = create_async_engine(f"sqlite+aiosqlite:///{path}")
    db_activity.watch(watched.sync_engine)
    try:
        async with watched.begin() as conn:
            await conn.execute(text("SELECT 1"))
            await asyncio.sleep(0.15)
            (held,) = await db_activity.held()
        await asyncio.sleep(0.05)
        after = await db_activity.held()
    finally:
        await watched.dispose()
    assert "test_a_transaction_is_seen_while_it_is_held" in held["caller"]
    assert held["host"] == socket.gethostname() and held["process"]
    assert held["began"] and after == []


def test_generated_code_is_not_the_apps() -> None:
    """SQLAlchemy runs code it generates (``<string>``): never the caller,
    though it resolves under the project's root."""
    assert db_activity._app_path("<string>") is None
    assert db_activity._app_path(str(ROOT / "app" / "main.py")) == "app/main.py"


async def test_a_transaction_opened_while_this_task_holds_one_waits_on_itself(
    path: Path,
) -> None:
    """SQLite has one writer: a second transaction the same task opens while
    it holds the first waits out the busy timeout behind itself, then fails.
    Recorded as it opens, naming the line that opened it."""
    pytest.importorskip("aiosqlite")
    watched = create_async_engine(f"sqlite+aiosqlite:///{path}")
    db_activity.watch(watched.sync_engine)
    try:
        async with watched.begin() as first:
            await first.execute(text("SELECT 1"))
            async with watched.begin() as second:
                await second.execute(text("SELECT 1"))
    finally:
        await watched.dispose()
    waits = [e for e in await _recorded() if e["kind"] == "self_wait"]
    assert len(waits) == 1
    assert "waits_on_itself" in waits[0]["caller"]


def test_the_activity_view_says_it_plainly() -> None:
    from app.services.system import ui_database

    event = {"kind": "self_wait", "seconds": None, "process": "p", "caller": "c"}
    (row,) = ui_database.activity([event | {"at": "2026-10-09T12:00:00+00:00"}])
    assert row["what"] == "Waits on itself"


async def test_a_short_transaction_is_never_published(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
    await asyncio.sleep(0.1)
    assert await db_activity.held() == []


async def test_a_write_that_found_it_locked_names_who_waited(
    engine: Engine, path: Path
) -> None:
    holder = sqlite3.connect(path)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(OperationalError), engine.begin() as conn:
            conn.execute(text("CREATE TABLE t (x INTEGER)"))
    finally:
        holder.rollback()
        holder.close()
    locked = [e for e in await _recorded() if e["kind"] == "locked"]
    assert locked and "names_who_waited" in locked[0]["caller"]


async def test_zero_turns_it_off(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(settings.__dict__, "DATABASE_SLOW_TRANSACTION_SECONDS", 0)
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
        time.sleep(0.06)
    assert await _recorded() == []


async def test_the_database_health_carries_the_hour_by_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What Illiana reads (``health``): the last hour grouped by the code
    behind it, never the rows, so a busy hour still fits."""
    from app.services.system import health_db

    checked = ComponentStatus(name="database", message="Connected", metadata={"a": 1})
    monkeypatch.setattr(health_db, "_check_engine", AsyncMock(return_value=checked))
    await _kept(_event("a.py:1 in f", seconds=3.0, ago=60))
    status = await health_db.check_database_health()
    activity = status.metadata["activity"]
    assert activity["window_s"] == 3600
    assert [g["code"] for g in activity["by_code"]] == ["a.py:1 in f"]


async def test_what_happened_outlasts_the_hour() -> None:
    """Kept for the retention (a week by default), as container history is,
    and read by window."""
    await _kept(_event("old.py:1 in f", ago=2 * 3600), _event("new.py:1 in g", ago=60))
    assert [e["caller"] for e in await db_activity.recent(3600)] == ["new.py:1 in g"]
    assert [e["caller"] for e in await db_activity.recent(6 * 3600)] == [
        "new.py:1 in g",
        "old.py:1 in f",
    ]


async def test_past_the_retention_it_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(settings.__dict__, "DATABASE_ACTIVITY_RETENTION_SECONDS", 600)
    await _kept(_event("old.py:1 in f", ago=900), _event("new.py:1 in g", ago=60))
    assert [e["caller"] for e in await db_activity.recent(3600)] == ["new.py:1 in g"]


async def test_a_window_reads_back_only_as_far_as_it_reaches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The newest first, a slice at a time (health asks for the hour every
    few seconds; the list keeps a week): it reads further back while the
    slice is still inside the window, and stops past it."""
    monkeypatch.setattr(db_activity, "FIRST_READ", 2)
    reads: list[int | None] = []
    listed = get_cache().listed

    async def counted(key: str, newest: int | None = None) -> list[object]:
        reads.append(newest)
        return await listed(key, newest)

    monkeypatch.setattr(get_cache(), "listed", counted)
    await _kept(
        _event("old.py:1 in f", ago=2 * 3600),
        *(_event(f"new.py:{n} in g", ago=60 + n) for n in range(5)),
    )
    assert len(await db_activity.recent(3600)) == 5
    assert reads == [2, 8]


def test_grouped_by_code_the_longest_held_first() -> None:
    events = [
        _event("ingest.py:330 in refresh", seconds=2.2),
        _event("ingest.py:330 in refresh", seconds=7.7, ago=120),
        _event("pages.py:523 in sitemap", seconds=78.7, process="webserver:24"),
        _event("jobs.py:40 in score", seconds=None, kind="locked"),
    ]
    groups = db_activity.grouped(events)
    assert [g["code"] for g in groups] == [
        "pages.py:523 in sitemap",
        "ingest.py:330 in refresh",
        "jobs.py:40 in score",
    ]
    ingest = groups[1]
    assert (ingest["count"], ingest["held_s"], ingest["longest_s"]) == (2, 9.9, 7.7)
    assert ingest["last"] == events[0]["at"]
    assert groups[2]["kinds"] == ["locked"]
    assert groups[0]["processes"] == ["webserver"]


async def test_the_summary_fits_what_illiana_is_given() -> None:
    """``health`` drops a detail longer than ``DETAIL_CHARS``: the summary
    keeps the costliest code sites, however busy the hour."""
    import json

    from app.services.system.node_now import DETAIL_CHARS

    long = "app/services/search/pypi_daily_ingest.py:{} in refresh_pypi_daily"
    await _kept(*(_event(long.format(n), seconds=2.0 + n) for n in range(50)))
    summary = await db_activity.summary()
    assert len(json.dumps(summary)) <= DETAIL_CHARS
    assert summary["by_code"][0]["code"] == long.format(49)


def test_a_statement_is_a_hop_to_the_database_and_to_its_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counted where it runs (``edges``), from the code that ran it, and
    from that part to each table, a failed one too."""
    import sqlalchemy as sa

    from app.core import edges

    engine = sa.create_engine("sqlite://")
    db_activity.watch(engine)
    notes = sa.Table("notes", sa.MetaData(), sa.Column("id", sa.Integer))
    notes.metadata.create_all(engine)
    edges.reset()
    monkeypatch.setattr(edges, "on_stack", lambda **_: (["service:finance"], []))

    with engine.connect() as conn:
        conn.execute(sa.select(notes)).all()
        with pytest.raises(sa.exc.OperationalError):
            conn.execute(sa.select(sa.table("gone", sa.column("id")))).all()

    seen = edges._seen
    assert seen[("service:finance", "component:database")].count == 2
    assert seen[("service:finance", "object:notes")].count == 1
    assert seen[("service:finance", "object:gone")].errors == 1
    edges.reset()
