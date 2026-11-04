"""What a page declares an agent may do on it, and the turn that holds it.

A page lists its targets: a part of it by its element id, a line saying
what it is (all the agent knows of it), and the page's own actions on it
besides scrolling to it and highlighting it (a stack laid out in a
builder, say), each with the value it takes. A chat mount keys its pages
by path (``ChatSurface.pages``) and the chat says which one it is on.

A turn on a declared page holds it and what carries an action to it (the
stream, or a call's socket): ``page_stage``. The AI service's
``page_action`` tool checks each action against the page and sends it.
"""

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.core.hooks import bound

# What every target takes: the page applies these itself (chat.js).
BUILT_IN = ("scroll", "highlight")


@dataclass(frozen=True)
class PageAction:
    """An action of the page's own on one target: its name, what it does
    (for the agent) and the value it takes, checked before the page gets
    it. The page's code handles it (a ``page-action`` DOM event)."""

    name: str
    about: str
    value: type[BaseModel]


@dataclass(frozen=True)
class PageTarget:
    """A part of the page an agent may point at: its element id, and what
    it is in one line, which is all the agent knows of it."""

    id: str
    about: str
    actions: tuple[PageAction, ...] = ()

    def action(self, name: str) -> PageAction | None:
        return next((a for a in self.actions if a.name == name), None)


@dataclass(frozen=True)
class Page:
    """Every target a page declares."""

    targets: tuple[PageTarget, ...]

    def get(self, target_id: str) -> PageTarget | None:
        return next((t for t in self.targets if t.id == target_id), None)

    def target(self, target_id: str) -> str:
        """A declared target's id, for the page's markup (the ``page_target``
        macro): one the page does not declare fails the render, so the
        markup and the declaration cannot drift apart."""
        if self.get(target_id) is None:
            raise KeyError(f"The page declares no target {target_id!r}")
        return target_id


# What carries an action to the page: the stream, or the call's socket.
Send = Callable[[dict[str, Any]], Awaitable[None]]
_staged: ContextVar[tuple[Page, Send] | None] = ContextVar("page", default=None)


def page_stage(page: Page | None, send: Send) -> AbstractContextManager[None]:
    """The turn wrapper: the page the turn is on (None: none declared) and
    what carries an action to it, for the agent built and the tools run
    inside."""
    return bound(_staged, (page, send) if page else None)


def staged_page() -> tuple[Page, Send] | None:
    """The page this turn is on and what carries an action to it, if any."""
    return _staged.get()
