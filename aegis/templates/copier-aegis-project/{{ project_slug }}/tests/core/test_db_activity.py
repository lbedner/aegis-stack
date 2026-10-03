"""Database activity (``app.core.db_activity``): a transaction held past
``DATABASE_SLOW_TRANSACTION_SECONDS``, and a write that found the database
locked, are recorded with the process and the app code behind them, for the
Database pages. Against a real SQLite file: the lock is SQLite's own."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
import sqlite3
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core import db_activity
from app.core.cache import get_cache
from app.core.config import settings
from app.services.system.models import ComponentStatus


@pytest.fixture(autouse=True)
async def clean(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setitem(settings.__dict__, "DATABASE_SLOW_TRANSACTION_SECONDS", 0.05)
    await get_cache().invalidate_prefix(db_activity.PREFIX)
    yield
    await get_cache().invalidate_prefix(db_activity.PREFIX)


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
    return await db_activity.recent()


async def test_a_transaction_held_too_long_names_its_caller(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("SELECT 1"))
        time.sleep(0.1)
    (event,) = await _recorded()
    assert event["kind"] == "slow" and event["seconds"] >= 0.1
    assert "test_a_transaction_held_too_long_names_its_caller" in event["caller"]
    assert event["process"]


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


async def test_the_database_health_carries_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.system import health_db

    checked = ComponentStatus(name="database", message="Connected", metadata={"a": 1})
    monkeypatch.setattr(health_db, "_check_engine", AsyncMock(return_value=checked))
    monkeypatch.setattr(
        db_activity, "recent", AsyncMock(return_value=[{"kind": "slow"}])
    )
    status = await health_db.check_database_health()
    assert status.metadata == {"a": 1, "activity": [{"kind": "slow"}]}
