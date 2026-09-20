"""``fanout`` keeps the three promises a bare ``gather`` does not.

The ceiling, the ordering and the per-item failure are the whole reason
this exists rather than five inline lines at each call site, so each one
is asserted directly.
"""

from __future__ import annotations

import asyncio

import pytest

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
