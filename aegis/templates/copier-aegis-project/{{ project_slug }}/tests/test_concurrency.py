"""``fanout`` keeps the three promises a bare ``gather`` does not.

The ceiling, the ordering and the per-item failure are the whole reason
this exists rather than five inline lines at each call site, so each one
is asserted directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import signal
import time

import pytest

from app.core import concurrency
from app.core.concurrency import fanout


async def test_results_come_back_in_input_order() -> None:
    """Not completion order. The slowest item is first on purpose."""

    async def work(n: int) -> int:
        await asyncio.sleep((10 - n) / 1000)
        return n * 2

    outcomes = await fanout(work, [1, 2, 3, 4], limit=4)

    assert [o.value for o in outcomes] == [2, 4, 6, 8]


async def test_the_limit_is_actually_a_ceiling() -> None:
    """The point of the wrapper: 500 items must not open 500 sockets."""
    live = 0
    peak = 0

    async def work(n: int) -> int:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return n

    await fanout(work, range(30), limit=4)

    assert peak == 4, f"ran {peak} at once with limit=4"


async def test_one_failure_does_not_cancel_the_others() -> None:
    """A bare ``gather`` drops the whole batch on the first exception."""

    async def work(n: int) -> int:
        if n == 2:
            raise RuntimeError("page 2 is a scan of a thumb")
        return n

    outcomes = await fanout(work, [1, 2, 3], limit=3)

    assert [o.ok for o in outcomes] == [True, False, True]
    assert [o.value for o in outcomes if o.ok] == [1, 3]
    assert isinstance(outcomes[1].error, RuntimeError)
    assert "thumb" in str(outcomes[1].error)


async def test_a_cancelled_batch_stays_cancelled() -> None:
    """``CancelledError`` is not a per-item failure to report; swallowing
    it would make a cancelled task look like it completed."""

    async def work(n: int) -> int:
        await asyncio.sleep(10)
        return n

    task = asyncio.create_task(fanout(work, range(4), limit=2))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_no_items_is_no_work_and_no_error() -> None:
    async def work(n: int) -> int:  # pragma: no cover - must never run
        raise AssertionError("called with nothing to do")

    assert await fanout(work, [], limit=4) == []


async def test_a_limit_below_one_is_refused() -> None:
    """Silently clamping to 1 would turn a typo into a mysteriously
    sequential run."""

    async def work(n: int) -> int:
        return n

    with pytest.raises(ValueError, match="at least 1"):
        await fanout(work, [1], limit=0)


async def test_it_is_concurrent_at_all() -> None:
    """Ten items that sleep 50ms each take ~50ms, not ~500ms."""

    async def work(n: int) -> int:
        await asyncio.sleep(0.05)
        return n

    start = asyncio.get_running_loop().time()
    await fanout(work, range(10), limit=10)
    elapsed = asyncio.get_running_loop().time() - start

    assert elapsed < 0.2, f"took {elapsed:.3f}s; that is sequential"


class TestCpuBound:
    """CPU work runs in a thread, so the loop keeps serving (a worker's
    claim keep-alive and heartbeats run on it), and one piece of it at a
    time per process: the GIL runs one anyway, so more would only look
    parallel."""

    def test_the_loop_keeps_running_while_cpu_work_does(self) -> None:
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.005)

        async def go() -> None:
            beat = asyncio.create_task(ticker())
            await concurrency.cpu_bound(
                time.sleep, 0.2
            )  # holds its thread, not the loop
            beat.cancel()

        asyncio.run(go())
        assert ticks > 5

    def test_one_piece_runs_at_a_time(self) -> None:
        running = 0
        most = 0

        def work() -> None:
            nonlocal running, most
            running += 1
            most = max(most, running)
            time.sleep(0.02)
            running -= 1

        async def go() -> None:
            await asyncio.gather(*(concurrency.cpu_bound(work) for _ in range(5)))

        asyncio.run(go())
        assert most == 1


class TestBackground:
    async def test_the_task_is_held_until_it_ends(self) -> None:
        """The loop keeps only a weak reference: an unheld task can be
        collected before it runs."""
        done = asyncio.Event()

        async def work() -> None:
            await asyncio.sleep(0)
            done.set()

        task = concurrency.background(work())
        assert task in concurrency._background
        await done.wait()
        await asyncio.sleep(0)
        assert task not in concurrency._background

    async def test_a_failure_is_logged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logged: list[BaseException | None] = []
        monkeypatch.setattr(
            concurrency.logger,
            "error",
            lambda *_, exc_info=None, **__: logged.append(exc_info),
        )

        async def work() -> None:
            raise ValueError("boom")

        task = concurrency.background(work())
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert [type(e) for e in logged] == [ValueError]

    async def test_drain_ends_what_is_still_running(self) -> None:
        """At shutdown: work still in flight is cancelled and given the time
        to finish its own cleanup (a meeting marks itself left)."""
        cleaned: list[str] = []

        async def long_work() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0)
                cleaned.append("done")
                raise

        concurrency.background(long_work())
        await asyncio.sleep(0)

        await concurrency.drain(timeout=1)

        assert cleaned == ["done"] and not concurrency._background


class TestClosing:
    """A stream that would stay open (a page's live SSE) ends as the server
    starts shutting down, rather than be cut at its grace timeout and
    logged as an error on every reload (2026-10-24)."""

    async def test_a_stream_ends_when_the_server_starts_closing(self) -> None:
        sent: list[int] = []

        async def forever() -> AsyncIterator[int]:
            n = 0
            while True:
                n += 1
                yield n
                await asyncio.sleep(0.01)

        async def read() -> None:
            async for n in concurrency.until_closing(forever()):
                sent.append(n)

        reading = asyncio.create_task(read())
        await asyncio.sleep(0.03)
        concurrency.closing().set()
        await asyncio.wait_for(reading, timeout=1)
        assert sent and reading.done() and not reading.cancelled()

    async def test_a_reader_that_leaves_closes_the_stream(self) -> None:
        """The client gone mid-wait (its request cancelled): the stream's
        own cleanup runs, nothing left waiting on it."""
        cleaned: list[str] = []

        async def waits() -> AsyncIterator[int]:
            try:
                yield 1
                await asyncio.sleep(10)
                yield 2
            finally:
                cleaned.append("closed")

        async def read() -> None:
            async for _ in concurrency.until_closing(waits()):
                pass

        reading = asyncio.create_task(read())
        await asyncio.sleep(0.01)
        reading.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reading
        assert cleaned == ["closed"]

    async def test_a_stream_that_ends_first_ends_as_it_does(self) -> None:
        async def two() -> AsyncIterator[int]:
            yield 1
            yield 2

        assert [n async for n in concurrency.until_closing(two())] == [1, 2]

    async def test_the_stop_signal_closes_then_reaches_the_server(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The server's own handler still runs: it is what shuts it down."""
        heard: list[int] = []
        handlers: dict[int, object] = {
            signal.SIGINT: lambda number, frame: heard.append(number),
            signal.SIGTERM: lambda number, frame: heard.append(number),
        }
        monkeypatch.setattr(signal, "getsignal", handlers.get)
        monkeypatch.setattr(signal, "signal", handlers.__setitem__)
        monkeypatch.setattr(concurrency, "_watching", False)

        concurrency.watch_shutdown()
        handlers[signal.SIGTERM](signal.SIGTERM, None)  # type: ignore[operator]
        await asyncio.sleep(0)

        assert heard == [signal.SIGTERM]
        assert concurrency.closing().is_set()
