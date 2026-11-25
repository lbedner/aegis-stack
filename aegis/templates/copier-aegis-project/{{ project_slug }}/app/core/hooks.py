"""A listener bound where work runs (``Hook.watching``), told of what
happens inside (``Hook.tell``): nothing listens unless bound, a task
started inside carries it, one bound inside another's is told beside it,
and a listener that fails is logged, never the work's failure. An agent's steps (``app.core.steps``) and a service's own
changes (the runner's runs) are each one."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from app.core.log import logger

Listener = Callable[..., None]
T = TypeVar("T")


@contextmanager
def bound(var: ContextVar[T], value: T) -> Iterator[None]:
    """``var`` set to ``value`` inside, as it was after."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)


class Hook:
    """One kind of thing a listener can be told of, ``name``d in its log."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._listeners: ContextVar[tuple[Listener, ...]] = ContextVar(name, default=())

    def watching(self, listener: Listener) -> AbstractContextManager[None]:
        """What happens inside, to ``listener`` and any bound outside it (a
        meeting bot's card, and the chat turn it runs)."""
        return bound(self._listeners, (*self._listeners.get(), listener))

    @property
    def listened(self) -> bool:
        """Whether anyone listens here: what to tell need not be made else."""
        return bool(self._listeners.get())

    def tell(self, *what: Any) -> None:
        for listener in self._listeners.get():
            try:
                listener(*what)
            except Exception:
                logger.exception(f"A {self.name} listener failed")
