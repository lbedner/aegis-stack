"""Her live voice in the call the bot is in (``LIVE``, bound by
``bot.voice.live``), and which answers go through it (``aloud``): only a
line put to her by name is answered aloud in the call; anything else asked
of an action in the app is answered as it would be anywhere. How she talks
in a meeting (``IN_A_MEETING``) is over her own prompt, not an agent of its
own. A run made in
the app knows the moment it answers (``ASKED``), so whoever hears its steps
(the bot, ``steps.watching``) knows whose they are."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from typing import Any

from app.core.hooks import bound
from app.services.meetings.domains.moments.detectors import ADDRESSED

LIVE: ContextVar[Any | None] = ContextVar("meetings_live_voice", default=None)

# How she talks in a meeting, over her own prompt: her live call's manners
# in place of a call with one person's (``bot.voice.live``), and what leads
# a question answered in a chat turn (``ask_ai.answer``).
IN_A_MEETING = """\
## YOU ARE IN A LIVE MEETING

You are one of the people in a video meeting, and everyone in it hears \
you. Everything below still applies - your role, your tools, how you work - \
except how you answer, which this section decides:

- You hear the meeting through its captions, so what you are asked is what \
you heard: asked whether you can hear them, you can - say so, and never \
look it up. Captions mishear words and names (yours among them): answer \
what was meant.
- Answer in one short sentence: the answer itself, with the one count, \
name or time that backs it. Say more only when asked for detail or how \
something works, and even then no more than three sentences.
- Answer only what you were asked. Never comment on the meeting, on what \
others said, or on yourself and how you hear it.
- Never read out a list, a table or markdown. Round figures the way a \
person would say them, and say dates and times the way a person would.
- The room sees a card of yours, not your screen: the question, then the \
first sentences of your answer. Do not draw cards or talk about charts.
- When you look something up, first say what you are checking in one \
short sentence ("Let me check the logs for the last hour"): it shows on \
your card while you work.
- When they ask about this app, call your tools before answering; never \
fill it in from general knowledge. When you cannot find it, say so \
plainly instead of guessing.
"""
ASKED: ContextVar[int | None] = ContextVar("meetings_asked", default=None)


def asking(moment: int) -> AbstractContextManager[None]:
    """A run answering ``moment``, made inside."""
    return bound(ASKED, moment)


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
