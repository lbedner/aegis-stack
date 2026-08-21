"""Debounced async work for type-ahead inputs.

A search box that fires on every keystroke sends one request per letter,
and the answers can come back out of order - so the register ends up
showing results for "sta" after you finished typing "starbucks". This
control solves both halves: it waits for a pause before running, and it
drops any result that a newer keystroke has already superseded.
"""

import asyncio
from collections.abc import Awaitable, Callable
import contextlib

import flet as ft

# Long enough to swallow a normal typing rhythm, short enough that a pause
# feels like an answer rather than a wait.
DEFAULT_DEBOUNCE_SECONDS = 0.35


class Debouncer:
    """Runs the LATEST scheduled coroutine after a quiet period.

    Usage::

        self._debounce = Debouncer(page)
        ...
        self._debounce.schedule(self._load)      # on each keystroke
        self._debounce.run_now(self._load)       # on Enter

    ``is_current`` lets the work itself bail out when it has been
    superseded mid-flight - a cancelled task stops a PENDING run, but
    nothing can un-send a request already in the air.
    """

    def __init__(
        self, page: ft.Page, *, delay: float = DEFAULT_DEBOUNCE_SECONDS
    ) -> None:
        self._page = page
        self._delay = delay
        self._task: asyncio.Task | None = None
        self._sequence = 0

    @property
    def sequence(self) -> int:
        """Token for the run being scheduled; pass it to ``is_current``."""
        return self._sequence

    def is_current(self, sequence: int) -> bool:
        """True while ``sequence`` is still the newest scheduled run."""
        return sequence == self._sequence

    def schedule(self, work: Callable[[], Awaitable[None]]) -> None:
        """Run ``work`` once the input has been quiet for ``delay``."""
        self.cancel()
        self._sequence += 1
        sequence = self._sequence

        async def _run() -> None:
            try:
                await asyncio.sleep(self._delay)
            except asyncio.CancelledError:
                return
            if sequence == self._sequence:
                await work()

        if self._page is not None:
            self._task = self._page.run_task(_run)

    def run_now(self, work: Callable[[], Awaitable[None]]) -> None:
        """Skip the wait (Enter pressed): drop any pending run and go."""
        self.cancel()
        self._sequence += 1

        async def _run() -> None:
            await work()

        # ``page.run_task`` requires an actual coroutine FUNCTION - a bare
        # async method reference (``self._load``) already is one, but a
        # lambda wrapping a call with extra args (``lambda: self._load(x)``)
        # is a plain sync function that merely returns a coroutine, which
        # fails ``asyncio.iscoroutinefunction``'s assert. Wrapping in
        # ``_run`` here handles both shapes uniformly, same as ``schedule``
        # already does.
        if self._page is not None:
            self._task = self._page.run_task(_run)

    def cancel(self) -> None:
        """Drop a pending run. Safe to call when nothing is scheduled."""
        task = self._task
        self._task = None
        if task is not None and not task.done():
            with contextlib.suppress(RuntimeError):
                task.cancel()
