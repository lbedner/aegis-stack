"""The audit log (``app.components.database.audit``): every
``AuditEmitter.emit`` kept as a row beside its log line, written off the
caller so an action never waits on, or fails with, its own audit row."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlmodel import delete

from app.components.database import audit as log
from app.components.database.models.audit import AuditEvent
from app.core import audit
from app.core.concurrency import settle
from app.core.db import get_async_session

# The suite keeps no rows (``_audit_logs_only`` in conftest): these do.
KEEPER = audit.keeper


@pytest.fixture(autouse=True)
async def _kept(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setattr(audit, "keeper", KEEPER)
    yield
    await settle(timeout=5)  # a failed test never hangs the run
    async with get_async_session() as db:
        await db.exec(delete(AuditEvent))
        await db.commit()


async def test_an_emitted_event_is_kept_with_its_fields() -> None:
    await audit.audit_emitter.emit(
        "auth.login_failed",
        actor_email="ops@example.com",
        target_type="session",
        target_id="abc",
        ip_address="10.0.0.1",
        detail="Wrong password",
        attempts=3,
    )
    await settle()
    [row] = await log.recent()
    assert (row.event_type, row.actor_email, row.target_type, row.target_id) == (
        "auth.login_failed",
        "ops@example.com",
        "session",
        "abc",
    )
    assert (row.ip_address, row.detail, row.context) == (
        "10.0.0.1",
        "Wrong password",
        {"attempts": 3},
    )


async def test_a_credential_never_reaches_the_log() -> None:
    await audit.audit_emitter.emit(
        "secrets.set",
        detail="OPENAI_API_KEY=sk-abcdefghijklmnop",
        api_key="sk-abcdefghijklmnop",
        sent={"note": "Bearer abcdefghijkl"},
    )
    await settle()
    [row] = await log.recent()
    kept = f"{row.detail} {row.context}"
    assert "abcdefghijk" not in kept
    assert row.context["api_key"] == "[redacted]"


@pytest.mark.queryspy(allow_n_plus_one=True)  # before the write, then after
async def test_the_caller_never_waits_on_the_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On SQLite a caller holding its session while it waited on a second
    writer would hold the lock that writer needs."""
    free = asyncio.Event()

    async def held(event: dict[str, Any]) -> None:
        await free.wait()
        await log.keep(event)

    monkeypatch.setattr(audit, "keeper", lambda: held)
    await asyncio.wait_for(audit.audit_emitter.emit("auth.logout"), timeout=1)
    assert await log.recent() == []
    free.set()
    await settle()
    assert [row.event_type for row in await log.recent()] == ["auth.logout"]


async def test_a_write_held_behind_an_open_session_lands_after_it() -> None:
    async with get_async_session() as db:
        db.add(AuditEvent(event_type="held.open"))
        await db.flush()
        await asyncio.wait_for(audit.audit_emitter.emit("auth.login"), timeout=1)
        await db.commit()
    await settle()
    assert {row.event_type for row in await log.recent()} == {"held.open", "auth.login"}


async def test_a_write_that_fails_never_fails_the_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(event: dict[str, Any]) -> None:
        raise RuntimeError("database gone")

    monkeypatch.setattr(audit, "keeper", lambda: broken)
    await audit.audit_emitter.emit("auth.login")
    await settle()


@pytest.mark.queryspy(allow_n_plus_one=True)  # one read per filter
async def test_recent_is_newest_first_and_filters_by_kind_and_actor() -> None:
    for kind, who in (
        ("auth.login", "a@example.com"),
        ("secrets.set", "a@example.com"),
        ("auth.logout", "b@example.com"),
    ):
        await audit.audit_emitter.emit(kind, actor_email=who)
        await settle()
    assert [r.event_type for r in await log.recent()] == [
        "auth.logout",
        "secrets.set",
        "auth.login",
    ]
    assert [r.event_type for r in await log.recent(kind="auth.")] == [
        "auth.logout",
        "auth.login",
    ]
    assert [r.event_type for r in await log.recent(actor="a@example.com")] == [
        "secrets.set",
        "auth.login",
    ]
    assert len(await log.recent(limit=1)) == 1
