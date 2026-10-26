"""Her live voice in the call the bot is in (``LIVE``, bound by
``bot.voice.live``), and which answers go through it (``aloud``): only a
line put to her by name is answered aloud in the call; anything else asked
of an action in the app is answered as it would be anywhere."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.services.meetings.domains.moments.detectors import ADDRESSED

LIVE: ContextVar[Any | None] = ContextVar("meetings_live_voice", default=None)


@contextmanager
def aloud(kind: str) -> Iterator[None]:
    """A run on a moment of ``kind``: with her live voice where it is a
    line put to her by name, without it otherwise."""
    if kind == ADDRESSED:
        yield
        return
    token = LIVE.set(None)
    try:
        yield
    finally:
        LIVE.reset(token)
