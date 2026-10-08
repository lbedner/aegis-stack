"""Collector input identities and bounded replay retain real repeats."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.components.backend.error_tracking import collector as collector_module
from app.components.backend.error_tracking.collector import Collector
from app.components.backend.error_tracking.source import SourceReader
from app.core.runtime import Instance, RuntimeUnavailableError, parse_log_line


def test_same_timestamp_ordinals_survive_replay() -> None:
    instance = Instance("id", "server", "webserver", "running")
    identities = []
    for _ in range(2):
        reader = SourceReader(instance, "server")
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S") + ".123456789Z"
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
    monkeypatch.setattr(collector, "_connection", connect)
    monkeypatch.setattr(
        collector_module, "asyncio", SimpleNamespace(**vars(asyncio) | {"sleep": sleep})
    )
    with pytest.raises(asyncio.CancelledError):
        await collector.source(
            Instance("id", "server", "webserver", "running"), "server"
        )
    assert waits[1] > 2 and waits[2] < 2
