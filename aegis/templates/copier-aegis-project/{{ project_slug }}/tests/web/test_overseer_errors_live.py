"""Independent viewers and race-free retained-state reconciliation."""

import asyncio

import pytest

from app.components.web_frontend import overseer_errors
from app.services.system import ui_errors
from app.services.system.errors.store import ErrorStore
from tests._error_store import occurrence


@pytest.fixture(autouse=True)
def _viewing(store: ErrorStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every stream here reads ``store``, with no runtime behind the page."""

    async def no_sources() -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(overseer_errors, "repository", lambda: store)
    monkeypatch.setattr(overseer_errors, "unavailable_reason", lambda: None)
    monkeypatch.setattr(overseer_errors, "_sources", no_sources)


async def test_two_viewers_rebuild_after_one_notification(
    store: ErrorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = occurrence("first")
    await store.insert(first)
    streams = [overseer_errors.updates({}), overseer_errors.updates({})]
    try:
        snapshots = [await anext(stream) for stream in streams]
        assert snapshots[0] == snapshots[1]
        await store.insert(first.model_copy(update={"id": "second"}))
        updated = await asyncio.gather(
            *(asyncio.wait_for(anext(stream), 4) for stream in streams)
        )
        assert updated[0] == updated[1]
        assert "Matching occurrences" in updated[0] and ">2</td>" in updated[0]
        assert (await store.issues())[0].count == 2
    finally:
        for stream in streams:
            await stream.aclose()


async def test_notification_during_snapshot_is_not_lost(
    store: ErrorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = ui_errors.load_list
    first = True

    async def racing(
        repository: ErrorStore, query: dict[str, str]
    ) -> dict[str, object]:
        nonlocal first
        snapshot = await load(repository, query)
        if first:
            first = False
            await store.insert(occurrence("race"))
        return snapshot

    monkeypatch.setattr(ui_errors, "load_list", racing)
    stream = overseer_errors.updates({})
    try:
        assert "No matching retained errors" in await anext(stream)
        assert "failed" in await asyncio.wait_for(anext(stream), 4)
    finally:
        await stream.aclose()


async def test_trimmed_reconnect_uses_retained_history(
    store: ErrorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await store.insert(occurrence("retained"))
    await store.client.delete(store.notifications)
    stream = overseer_errors.updates({})
    try:
        assert "failed" in await anext(stream)
    finally:
        await stream.aclose()


async def test_quiet_expiry_reconciles_without_a_notification(
    store: ErrorStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(overseer_errors, "RECONCILE_SECONDS", 0.05)
    store.retention_seconds = 1
    await store.insert(occurrence("short-lived"))
    stream = overseer_errors.updates({})
    try:
        assert "failed" in await anext(stream)
        await asyncio.sleep(1.1)
        await store.prune()  # the collector's tick; reads never prune
        assert "No matching retained errors" in await asyncio.wait_for(anext(stream), 3)
    finally:
        await stream.aclose()
