"""The chat's voice dialog never waits on its own write lock.

Its route reads the voice profiles through the request's session, which
then holds the write lock (``app.core.db`` begins IMMEDIATE). The live-call
rows read the model catalog and the vendors' marks through sessions of
their own: opened as writers, they waited the whole busy timeout behind the
request and failed it, a 500 (2026-11-21); the call setup's line reads
the catalog's prices too (``call_setup``), and waited the same way before
the dialog opened. A read takes no write lock (``read_only``), so it
cannot wait, whoever asks.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.components.web_frontend.chat_surface import marks
from app.services.ai.domains.llm.catalog import list_models
from app.services.ai.domains.spend import calls, recording


@pytest.mark.usefixtures("holder")
async def test_the_catalog_read_does_not_wait() -> None:
    assert await list_models(mode="realtime") == []


@pytest.mark.usefixtures("holder")
async def test_the_vendor_marks_read_does_not_wait() -> None:
    assert await marks({"openai": ("openai",)}) == {}


@pytest.mark.usefixtures("holder")
async def test_the_price_read_does_not_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed read is logged and priced as unknown: it must not fail."""

    def failed(*_: Any, **said: Any) -> None:
        raise AssertionError(said.get("error"))

    monkeypatch.setattr(recording.logger, "warning", failed)
    assert await calls.realtime_price("gpt-live-1") is None
    assert await recording.speech_cost("gpt-transcribe", input_seconds=60) == 0
