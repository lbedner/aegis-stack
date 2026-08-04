"""Tests for the type-ahead debouncer.

A search box that fires per keystroke is both wasteful and WRONG: the
answers can land out of order, so the slowest early request paints last
and the view settles on results for a prefix of what was typed. These
cover the quiet-period behaviour and the supersede guard.
"""

import asyncio

import pytest

from app.components.frontend.controls.debounce import Debouncer


class FakePage:
    """Minimal stand-in for ``ft.Page.run_task``."""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []

    def run_task(self, coro_or_func):
        task = asyncio.ensure_future(coro_or_func())
        self.tasks.append(task)
        return task


@pytest.mark.asyncio
async def test_only_the_last_keystroke_runs() -> None:
    page = FakePage()
    debounce = Debouncer(page, delay=0.01)
    calls: list[str] = []

    def work(label: str):
        async def _run() -> None:
            calls.append(label)

        return _run

    for label in ("s", "st", "sta", "star"):
        debounce.schedule(work(label))
    await asyncio.sleep(0.05)

    assert calls == ["star"]  # four keystrokes, one request


@pytest.mark.asyncio
async def test_enter_skips_the_wait() -> None:
    page = FakePage()
    debounce = Debouncer(page, delay=5)  # long enough that a wait would hang
    calls: list[str] = []

    async def work() -> None:
        calls.append("ran")

    debounce.run_now(work)
    await asyncio.sleep(0.01)

    assert calls == ["ran"]


@pytest.mark.asyncio
async def test_pending_run_is_dropped_by_a_newer_one() -> None:
    page = FakePage()
    debounce = Debouncer(page, delay=0.01)
    calls: list[str] = []

    async def slow() -> None:
        calls.append("slow")

    async def fast() -> None:
        calls.append("fast")

    debounce.schedule(slow)
    debounce.run_now(fast)  # Enter mid-typing
    await asyncio.sleep(0.05)

    assert calls == ["fast"]


@pytest.mark.asyncio
async def test_in_flight_work_can_tell_it_was_superseded() -> None:
    """Cancelling stops a PENDING run; nothing un-sends a request already
    in the air. ``is_current`` is how that work bails before painting."""
    page = FakePage()
    debounce = Debouncer(page, delay=0)
    painted: list[str] = []

    async def load(label: str, sequence: int) -> None:
        await asyncio.sleep(0.02)  # the request
        if debounce.is_current(sequence):
            painted.append(label)

    first = debounce.sequence
    task = asyncio.ensure_future(load("stale", first))
    debounce.schedule(lambda: load("fresh", debounce.sequence))
    await asyncio.sleep(0.1)
    await task

    assert painted == ["fresh"]  # the stale response never painted


@pytest.mark.asyncio
async def test_cancel_is_safe_when_nothing_is_scheduled() -> None:
    debounce = Debouncer(FakePage(), delay=0.01)
    debounce.cancel()
    debounce.cancel()  # idempotent
