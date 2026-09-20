"""Running independent work concurrently, with a ceiling.

The slow thing in this stack is rarely the server and rarely the event
loop. It is a ``for`` loop over items that do not depend on each other,
each one waiting on a network call or a subprocess while the next one
waits its turn.

``asyncio.gather`` is the answer to that, but used bare it gets three
things wrong often enough to be worth wrapping once:

* **No ceiling.** A 500-page document becomes 500 concurrent OCR
  subprocesses, or 500 requests at a provider that rate-limits at ten.
* **First failure cancels the batch.** ``return_exceptions=True`` fixes
  that, and is easy to forget.
* **Results come back positionally**, which is right, but only if every
  caller remembers to keep the inputs aligned.

So: one spelling, and the concurrency limit is a parameter rather than a
thing each call site reinvents.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import NamedTuple, TypeVar

T = TypeVar("T")
R = TypeVar("R")

# Enough to hide latency, small enough that a provider does not notice.
# Every caller should pass its own; this is what to use when there is no
# reason to think otherwise.
DEFAULT_LIMIT = 8


class Outcome(NamedTuple):
    """What one item produced: a value, or the exception it raised.

    Explicit rather than a bare ``value | Exception`` union, because the
    union makes ``isinstance`` checks the caller's problem and reads
    identically whether or not they remembered to write one.
    """

    value: object
    error: BaseException | None

    @property
    def ok(self) -> bool:
        return self.error is None


async def fanout(
    fn: Callable[[T], Awaitable[R]],
    items: Iterable[T],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[Outcome]:
    """Run ``fn`` over ``items``, at most ``limit`` at a time.

    Results come back in input order, not completion order. A failing
    item is an ``Outcome`` carrying its exception; the rest still run.
    ``CancelledError`` is not caught - a cancelled batch stays cancelled.

    ``fn`` must be a coroutine function. Wrap blocking work in
    ``asyncio.to_thread`` at the call site, where it is obvious that a
    thread is involved.
    """
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    gate = asyncio.Semaphore(limit)
    listed: Sequence[T] = list(items)

    async def guarded(item: T) -> Outcome:
        async with gate:
            try:
                return Outcome(await fn(item), None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
                return Outcome(None, exc)

    if not listed:
        return []
    return list(await asyncio.gather(*(guarded(item) for item in listed)))
