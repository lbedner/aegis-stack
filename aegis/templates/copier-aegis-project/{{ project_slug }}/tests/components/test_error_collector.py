"""Collector input identities and bounded replay retain real repeats."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.components.backend.error_tracking import collector as collector_module
from app.components.backend.error_tracking.collector import Collector
from app.components.backend.error_tracking.source import SourceReader
from app.core.runtime import (
    ContainerEvent,
    Instance,
    RuntimeUnavailableError,
    parse_log_line,
)
from app.services.system.errors.models import ErrorOccurrence
from tests._fake_runtime import FakeRuntime, use_runtime


def test_same_timestamp_ordinals_survive_replay() -> None:
    instance = Instance("id", "server", "webserver", "running")
    identities = []
    # One stamp for both reads: a replay is the same lines, and a second
    # ticking over between reads would make them different lines.
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S") + ".123456789Z"
    for _ in range(2):
        reader = SourceReader(instance, "server")
        for raw in ("INFO: hello", "ERROR: failed", "ERROR: failed"):
            identities.extend(
                reader.feed(parse_log_line(stamp + " " + raw, "stderr"), now=0)
            )
        identities.extend(reader.flush())
    assert identities[0].id != identities[1].id
    assert identities[0].id == identities[2].id
    assert identities[1].ordinal == 2


def test_pending_trace_and_fields_are_bounded() -> None:
    reader = SourceReader(Instance("id", "server", "webserver", "running"), "server")
    reader.feed(parse_log_line("ERROR: failed", "stderr"), now=0)
    for _ in range(100):
        reader.feed(parse_log_line("  " + "x" * 1000, "stderr"), now=0)
    events = reader.flush()
    assert len(events) == 1 and events[0].truncated
    assert len(events[0].model_dump_json().encode()) <= 65536


async def test_a_stream_that_ends_cleanly_reconnects_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backoff is for a source that keeps failing: one that connected and
    ended normally (a restart, a rotation) starts over from the shortest wait."""
    outcomes = iter(
        [RuntimeUnavailableError("down"), RuntimeUnavailableError("down"), None]
    )
    waits: list[float] = []

    async def connect(*_: object) -> None:
        if (outcome := next(outcomes)) is not None:
            raise outcome

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError

    collector = Collector(store=None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        collector_module, "asyncio", SimpleNamespace(**vars(asyncio) | {"sleep": sleep})
    )
    with pytest.raises(asyncio.CancelledError):
        await collector._retrying("id", connect)
    assert waits[1] > 2 and waits[2] < 2


async def test_a_container_out_of_memory_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lease owner reads Docker's ``oom`` events over the retention
    window: the webserver that ran out restarts with this collector in it,
    after the event. A container with no page of its own is left out, as
    its logs are."""
    at = datetime.now(UTC)
    fake = use_runtime(
        monkeypatch,
        FakeRuntime(
            ran_out=[
                ContainerEvent("a1", "app-webserver-1", "webserver", at),
                ContainerEvent("b2", "app-socket-proxy-1", "socket-proxy", at),
            ]
        ),
    )
    stored: list[ErrorOccurrence] = []

    async def insert(event: ErrorOccurrence, *, token: str) -> str:
        stored.append(event)
        return "inserted"

    store = SimpleNamespace(retention_seconds=3600, insert=insert)
    await Collector(store)._memory()  # type: ignore[arg-type]

    assert [(e.container_name, e.page) for e in stored] == [
        ("app-webserver-1", "server")
    ]
    (since,) = fake.ran_out_since
    assert since is not None and (at - since).total_seconds() >= 3600 - 5
