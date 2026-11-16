"""A quiet stream is not a broken one: it says so while it is quiet.

Between the first frame and the first token a stream can send nothing for
tens of seconds (a local model loading), which looks exactly like a hang.
``announce_waiting`` names the silence, over any async iterator, and only
while it lasts: a stream that is answering has nothing to explain.
"""

import asyncio
from collections.abc import AsyncIterator
import contextvars

import pytest

from app.core.concurrency import Waiting, announce_waiting


async def _quiet(delay: float, *items: str) -> AsyncIterator[str]:
    """A source that stalls before its first item."""
    await asyncio.sleep(delay)
    for item in items:
        yield item


async def _all(source: AsyncIterator[object]) -> list[object]:
    return [item async for item in source]


class TestASilentStreamSaysSo:
    async def test_a_stall_before_the_first_item_is_announced(self) -> None:
        out = await _all(announce_waiting(_quiet(0.25, "hello"), every=0.05))

        assert any(isinstance(f, Waiting) for f in out)
        assert out[-1] == "hello"

    async def test_a_stream_that_never_stalls_is_left_alone(self) -> None:
        assert await _all(announce_waiting(_quiet(0, "a", "b"), every=5)) == [
            "a",
            "b",
        ]

    async def test_the_wait_is_measured_from_the_last_item(self) -> None:
        """A mid-stream pause reports its own length, not the stream's age."""

        async def pause_in_the_middle() -> AsyncIterator[str]:
            yield "a"
            await asyncio.sleep(0.25)
            yield "b"

        out = await _all(announce_waiting(pause_in_the_middle(), every=0.05))

        waits = [f for f in out if isinstance(f, Waiting)]
        assert waits and max(w.seconds for w in waits) < 1

    async def test_an_empty_stream_ends(self) -> None:
        async def nothing() -> AsyncIterator[str]:
            return
            yield  # pragma: no cover

        assert await _all(announce_waiting(nothing(), every=5)) == []

    async def test_the_source_failure_is_the_callers_to_see(self) -> None:
        async def breaks() -> AsyncIterator[str]:
            yield "a"
            raise RuntimeError("provider said no")

        with pytest.raises(RuntimeError, match="provider said no"):
            await _all(announce_waiting(breaks(), every=5))

    async def test_a_reader_that_goes_away_stops_the_item_in_flight(self) -> None:
        """Stop, or a closed tab: the wait is abandoned and so is the work
        it was waiting on, or the model call runs on for no one."""
        stopped = asyncio.Event()

        async def slow() -> AsyncIterator[str]:
            try:
                await asyncio.sleep(5)
                yield "late"
            finally:
                stopped.set()

        stream = announce_waiting(slow(), every=0.05)
        assert isinstance(await anext(stream), Waiting)
        await stream.aclose()

        await asyncio.wait_for(stopped.wait(), timeout=1)


class TestAPauseCanSayWhy:
    async def test_the_explainer_is_asked_once_per_quiet_stretch(self) -> None:
        asked = 0

        async def explain() -> str:
            nonlocal asked
            asked += 1
            return "loading"

        out = await _all(
            announce_waiting(_quiet(0.3, "hi"), every=0.05, explain=explain)
        )

        waits = [f for f in out if isinstance(f, Waiting)]
        assert len(waits) > 1
        assert asked == 1
        assert all(w.reason == "loading" for w in waits)

    async def test_an_explainer_that_fails_does_not_fail_the_turn(self) -> None:
        async def explain() -> str:
            raise RuntimeError("the engine is not listening")

        out = await _all(
            announce_waiting(_quiet(0.15, "hi"), every=0.05, explain=explain)
        )

        assert out[-1] == "hi"
        assert all(f.reason is None for f in out if isinstance(f, Waiting))

    async def test_the_explainer_sees_what_the_source_set(self) -> None:
        """What the turn knows by now (its model) is the explainer's to read."""
        model: contextvars.ContextVar[str] = contextvars.ContextVar("model")

        async def source() -> AsyncIterator[str]:
            model.set("qwen")
            await asyncio.sleep(0.15)
            yield "hi"

        async def explain() -> str:
            return model.get("unknown")

        out = await _all(announce_waiting(source(), every=0.05, explain=explain))

        assert {f.reason for f in out if isinstance(f, Waiting)} == {"qwen"}


class TestTheSourceKeepsItsContext:
    async def test_a_contextvar_set_and_reset_across_items_survives(self) -> None:
        """Each step runs in one context, so a token set while producing
        one item resets while producing a later one."""
        var: contextvars.ContextVar[str] = contextvars.ContextVar("probe")

        async def sets_then_resets() -> AsyncIterator[str]:
            token = var.set("in-flight")
            yield "first"
            await asyncio.sleep(0.15)
            yield "second"
            var.reset(token)
            yield "third"

        out = [
            f
            for f in await _all(announce_waiting(sets_then_resets(), every=0.05))
            if not isinstance(f, Waiting)
        ]

        assert out == ["first", "second", "third"]
