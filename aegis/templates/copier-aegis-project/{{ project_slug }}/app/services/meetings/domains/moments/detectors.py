"""What makes a line a moment, one detector per kind.

A detector reads one line as the bot writes it, and again each time its
caption grows, and says what the moment is (its text) or None. Registered
by kind, like tools: the meetings service registers ``question`` here.
Another service registers its own detectors and actions in its
``meeting_moments`` module (``app/services/<name>/meeting_moments.py``),
found on disk like its ``tools`` and imported before either is first read.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
import re

from app.core.discovery import import_modules_named

# The module another service registers its detectors and actions in.
EXTENSIONS = "meeting_moments"


@dataclass(frozen=True)
class Heard:
    """One line as a detector reads it: who said it, whether that is the
    owner, what was said so far, and everyone who has spoken in the call
    (by the names it gave them)."""

    line_id: int
    speaker: str
    text: str
    is_me: bool
    people: frozenset[str] = frozenset()


Detector = Callable[[Heard], str | None]

_detectors: dict[str, Detector] = {}
_titles: dict[str, str] = {}


def register_detector(
    kind: str, detector: Detector, *, title: str | None = None, replace: bool = False
) -> None:
    """Find moments of ``kind`` with ``detector``; ``title`` heads them
    where they are shown (``Questions``). A kind is registered once unless
    ``replace``."""
    if kind in _detectors and not replace:
        raise ValueError(f"A detector for {kind!r} is already registered")
    _detectors[kind] = detector
    _titles.pop(kind, None)
    if title:
        _titles[kind] = title


def unregister_detector(kind: str) -> None:
    _detectors.pop(kind, None)
    _titles.pop(kind, None)


@cache
def load_extensions() -> None:
    """Import every service's ``meeting_moments`` module, once."""
    import app.services as services

    import_modules_named(services, EXTENSIONS)


def title_of(kind: str) -> str:
    """What heads moments of ``kind``."""
    load_extensions()
    return _titles.get(kind, kind.replace("_", " ").capitalize())


def detectors() -> dict[str, Detector]:
    """Every registered detector, by kind."""
    load_extensions()
    return dict(_detectors)


# The kind the meetings service finds itself.
QUESTION = "question"
# What a question opens on, or a clause of it: who or what it asks, or
# the verb turned to ask it.
ASKING = frozenset(
    "who whom whose what what's when where where's why how which "
    "is isn't are aren't am was wasn't were weren't do don't does doesn't "
    "did didn't can can't could couldn't would wouldn't will won't should "
    "shouldn't shall have haven't has hasn't had may might anyone anybody".split()
)
# A statement asked at its end: ``..., right?``
TAGS = frozenset({"right", "correct"})
# What opens a clause in speech without saying anything.
FILLERS = frozenset(
    "um uh hmm okay ok so yeah yes well oh and but like wait alright".split()
)
# Fewer real words than this, past the fillers, is a sound, not a question.
FEWEST_WORDS = 3
SENTENCE = re.compile(r"[.!?]+")
WORD = re.compile(r"[a-z']+")


# Said to someone in the call: *you*, or asking their leave.
YOU = frozenset({"you", "your", "you're", "you've", "you'll", "yours"})
LEAVE = re.compile(r"\b(?:can|could|may|should) i\b")
# Said without speaking to anyone.
NOT_ADDRESSED = re.compile(r"\b(?:thank you|you know)\b")


def question(heard: Heard) -> str | None:
    """A question someone other than the owner asks for an answer: their
    line ending in a question mark, its last sentence asked as one
    (``asks``), and not asked of someone in the call (``asked_of_someone``).
    Captions end anything said with a rising tone in one."""
    text = heard.text.strip()
    if heard.is_me or not text.endswith("?"):
        return None
    if not asks(text) or asked_of_someone(text, heard.people - {heard.speaker}):
        return None
    return text


def _sentences(text: str) -> list[str]:
    """``text``'s sentences, its closing mark left off."""
    return SENTENCE.split(text.rstrip("?!. "))


def asked_of_someone(text: str, people: frozenset[str]) -> bool:
    """Whether the question (its last two sentences: captions break one
    mid-way) is put to a person: one of ``people`` named, *you*, or leave
    asked. Theirs to answer, not an agent's."""
    # ponytail: first names and second person; a question about someone
    # (``when did Tom ship it?``) reads as one put to them.
    said = " ".join(_sentences(text)[-2:]).lower()
    words = set(WORD.findall(NOT_ADDRESSED.sub(" ", said)))
    names = {first for person in people if len(first := person.split()[0].lower()) > 2}
    return bool(words & YOU or words & names or LEAVE.search(said))


def asks(text: str) -> bool:
    """Whether the last sentence of ``text`` asks: ``FEWEST_WORDS`` or more
    past the fillers, a clause opening on a word in ``ASKING``, or a tag
    (``TAGS``) closing it."""
    last = _sentences(text)[-1]
    clauses = [_words(clause) for clause in last.split(",")]
    if sum(len(clause) for clause in clauses) < FEWEST_WORDS:
        return False
    opens = any(clause and clause[0] in ASKING for clause in clauses)
    tagged = len(clauses[-1]) == 1 and clauses[-1][0] in TAGS
    return opens or tagged


def _words(clause: str) -> list[str]:
    """A clause's words, lowercased, the fillers it opens on left out."""
    words = WORD.findall(clause.lower())
    while words and words[0] in FILLERS:
        words.pop(0)
    return words


register_detector(QUESTION, question, title="Questions")
