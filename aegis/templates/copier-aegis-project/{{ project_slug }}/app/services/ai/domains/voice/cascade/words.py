"""The words of a chain call: how it opens, where a spoken answer's
sentences end, the caller's sounds of thinking, and the text a model's
stream adds."""

import re
from typing import Any

from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, TextPart, TextPartDelta

# How a call opens: said at once, while the model reads the call's context
# (``connection.CascadeConnection._open``). Fits a first call, a resumed one and one
# carried on alike.
OPENING = "Hi, I'm here. Go ahead."
# Where a sentence ends, as the chat's own voice splits a streamed answer.
ENDS = re.compile(r"(?<=[.!?])\s+|\n+")
# A turn of these alone is the caller thinking aloud: "Um" and "Hm." were
# each answered ("No rush, take your time") while they gathered the
# question (2026-11-22). Held, they lead the words that come next.
FILLERS = frozenset({"ah", "er", "erm", "hm", "hmm", "mm", "uh", "uhm", "um"})


def filler(words: str) -> bool:
    """Only sounds of thinking ("Um", "Hm."), no words (``FILLERS``)."""
    return set(re.findall(r"[a-z]+", words.lower())) <= FILLERS


def text_of(event: Any) -> str:
    """The answer's words an event of the stream adds, if any."""
    if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
        return event.part.content
    if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
        return event.delta.content_delta
    return ""
