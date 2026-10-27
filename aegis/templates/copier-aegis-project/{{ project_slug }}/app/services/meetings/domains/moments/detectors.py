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
from difflib import SequenceMatcher
from functools import cache
import re

from app.core.discovery import import_modules_named

# The module another service registers its detectors and actions in.
EXTENSIONS = "meeting_moments"


@dataclass(frozen=True)
class Heard:
    """One line as a detector reads it: who said it, whether that is the
    owner, what was said so far, everyone who has spoken in the call (by
    the names it gave them), the bot's name where this speaker may wake it
    (``addressee``; empty where they may not, or it is the bot's own), and
    whether it was said right after the bot spoke (``replying``)."""

    line_id: int
    speaker: str
    text: str
    is_me: bool
    people: frozenset[str] = frozenset()
    addressee: str = ""
    replying: bool = False


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
# What says nothing anywhere in speech, not only where a clause opens.
UMS = frozenset("uh um uhm er erm hmm ah".split())
# What opens a clause in speech without saying anything.
FILLERS = frozenset(
    "um uh hmm okay ok so yeah yes well oh and but like wait alright".split()
)
# Fewer real words than this, past the fillers, is a sound, not a question.
FEWEST_WORDS = 3
SENTENCE = re.compile(r"[.!?]+")
# Between one whole sentence and the next, its mark kept.
SENTENCES = re.compile(r"(?<=[.!?])\s+")
WORD = re.compile(r"[a-z']+", re.IGNORECASE)
# What a word is said as with a verb run on: how's, who're, what'd.
RUN_ON = re.compile(r"'(?:s|re|d|ll)$")


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
    if heard.is_me or not text.endswith("?") or addressed(heard):
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
    opens = any(clause and RUN_ON.sub("", clause[0]) in ASKING for clause in clauses)
    tagged = len(clauses[-1]) == 1 and clauses[-1][0] in TAGS
    return opens or tagged


def _words(clause: str) -> list[str]:
    """A clause's words, lowercased, the fillers it opens on left out."""
    words = WORD.findall(clause.lower())
    while words and words[0] in FILLERS:
        words.pop(0)
    return words


register_detector(QUESTION, question, title="Questions")


# The kind a line put to the bot by name is: it answers it, out loud.
ADDRESSED = "addressed"
# What a line opens on before her name and still says it to her.
GREETINGS = frozenset("hey hi hello hiya yo ok okay".split())
# A word asking for something done, opening what she is asked.
REQUESTS = frozenset(
    "tell show find check look give remind summarize summarise explain list "
    "pull read open walk please".split()
)
# How close a captioned word must be to her name: captions spell it as
# they hear it (Illiana, Iliana, Eliana).
NAME_LIKE = 0.75
ENDS = ("?", ".", "!")


# What Meet calls the bot's own captions, in its own page.
ITSELF = "You"
# How soon after the bot spoke a line is said back to it, needing no name.
FOLLOW_SECONDS = 8.0
# How soon after the bot's words (played, or captioned) a line of them is
# its own speech heard back (through the asker's microphone, captioned as
# theirs), not a reply: begun while it talks (a gap below zero), or just
# after, as captions run late.
ECHO_SECONDS = 1.5
# What is said back that answers nothing: a reply made only of these (and
# fillers) is not put to it.
THANKS = frozenset(
    "thanks thank you cool great got it nice perfect awesome sure no yep nope "
    "right gotcha good".split()
)


def addressee(speaker: str, is_me: bool, bot: str, anyone: bool) -> str:
    """The bot's name for a line ``speaker`` said (``Heard.addressee``):
    empty where they may not wake it (only its owner may, and they are not
    it) or the line is the bot's own."""
    return bot if not its_own(speaker, bot) and (anyone or is_me) else ""


def its_own(speaker: str, bot: str) -> bool:
    """Whether a line ``speaker`` said is the bot's own."""
    return speaker in (ITSELF, bot)


# The line before a line, as whether it is said back to the bot is read:
# who said it, how long before this one began it ended, who last put
# something to the bot, and what it said.
Before = tuple[str, float, str, str]


def replying(before: Before | None, speaker: str, bot: str, text: str) -> bool:
    """Whether a line ``speaker`` said (``text``) is said back to the bot:
    the line before it (who said it, how long before this one began, who
    last put something to the bot, and what it said) is the bot's own,
    within ``FOLLOW_SECONDS``, answering ``speaker``. Someone else talking
    just after it is not, nor the bot's own words heard back while it is
    still talking (``echoes``, within ``ECHO_SECONDS``)."""
    if before is None:
        return False
    said, gap, asker, its_words = before
    back = its_own(said, bot) and gap <= FOLLOW_SECONDS and speaker == asker
    return back and not (gap <= ECHO_SECONDS and echoes(text, its_words))


def echoes(text: str, said: str) -> bool:
    """Whether ``text`` is a run of ``said``'s words, in order: its speech
    heard back ("Let me." of "Let me look that up.")."""
    theirs, its = WORD.findall(text.lower()), WORD.findall(said.lower())
    size = len(theirs)
    return bool(theirs) and any(
        its[at : at + size] == theirs for at in range(len(its) - size + 1)
    )


@cache  # captions say the same words over and over, on every look
def named(word: str, name: str) -> bool:
    """Whether ``word`` is ``name`` (its first name) as a caption spells it."""
    first = name.split()[0].lower() if name.strip() else ""
    return (
        bool(first) and SequenceMatcher(None, word.lower(), first).ratio() >= NAME_LIKE
    )


def mentions(text: str, name: str) -> bool:
    """Whether ``text`` says ``name`` anywhere (to her, or about her)."""
    return any(named(word, name) for word in WORD.findall(text.lower()))


def cut_at_name(text: str, name: str) -> list[str]:
    """``text`` cut before each sentence that says ``name``: one piece for
    each time it is spoken to (a speaker talking on stays one caption), the
    first what came before."""
    pieces = [""]
    for sentence in SENTENCES.split(text.strip()):
        if pieces[-1] and mentions(sentence, name):
            pieces.append(sentence)
        else:
            pieces[-1] = f"{pieces[-1]} {sentence}".strip()
    return pieces


def addressed(heard: Heard) -> str | None:
    """What a line asks of the bot, where it is put to it by name: opening
    on its name (after a greeting at most) or closing on it, said to its end,
    and asking something (``asks``) or for something done (``REQUESTS``).
    A line that names it in passing is about it, not to it. Said back to it
    (``replying``), the whole line is, its name or not, unless all it says
    is thanks (``THANKS``)."""
    text = heard.text.strip()
    if not heard.addressee or not text.endswith(ENDS):
        return None
    if heard.replying and not mentions(text, heard.addressee):
        return text if set(_words(text)) - THANKS - FILLERS else None
    ask = _past_name(text, heard.addressee)
    return None if ask is None else _asked(ask)


def put_to(text: str, name: str) -> str:
    """What ``text`` puts to ``name``, as a card shows it: its name off (with
    the greeting before it, or where it closes the line), the fillers it
    opens on, and its ums anywhere (``UMS``: captions mark a pause on one,
    and end the question on a "."), a question ending on "?" ("Uh, hey
    Illiana, are there any, uh? Errors." is "Are there any errors?"); a
    line without the name keeps all but its fillers. Done on the text,
    no model asked, so the card shows it at once."""
    said = text.strip()
    ask = _past_name(said, name)
    ask = _without_ums(said if ask is None else ask)
    while (first := WORD.match(ask)) and first.group().lower() in GREETINGS | FILLERS:
        ask = ask[first.end() :].lstrip(" ,.;:!-")
    if not ask:
        return said
    if ask.endswith(".") and asks(ask):
        ask = ask[:-1] + "?"
    return ask[:1].upper() + ask[1:]


def _without_ums(text: str) -> str:
    """``text`` without its ums, and what captions hung on them: the comma
    before one, and a capital after one they took for a sentence's end."""
    kept: list[str] = []
    lower = False
    for token in text.split():
        if token.strip(",.?!;:").lower() in UMS:
            if kept:
                kept[-1] = kept[-1].rstrip(",")
            lower = lower or token.endswith((".", "?", "!"))
            continue
        if lower and token[:1].isupper() and token != "I" and token[:2] != "I'":
            token = token[:1].lower() + token[1:]
        lower = False
        kept.append(token)
    return " ".join(kept)


def _past_name(text: str, name: str) -> str | None:
    """``text`` past ``name``: after it, where it opens on it (after a
    greeting at most), or before it, where it closes on it; None where the
    name is neither (said in passing, or not at all)."""
    words = list(WORD.finditer(text))
    at = next((i for i, w in enumerate(words) if named(w.group(), name)), None)
    if at is None:
        return None
    if all(w.group().lower() in GREETINGS | FILLERS for w in words[:at]):
        return text[words[at].end() :].lstrip(" ,.;:!-")
    if at == len(words) - 1:
        end = text[-1] if text.endswith(ENDS) else ""
        return text[: words[at].start()].rstrip(" ,;:-") + end
    return None


def _asked(ask: str) -> str | None:
    """``ask``, all of it, where any sentence of it asks (``asks``: a
    speaker talks on past the question, and captions mark a pause in one as
    its end), was captioned as asked (put to her by name, a rising "?" is
    enough: *if Redis goes down? what happens?*), or opens on a request;
    she reads the whole of it."""
    asking = "?" in ask or any(asks(sentence) for sentence in SENTENCES.split(ask))
    return ask if ask and (asking or set(_words(ask)[:1]) & REQUESTS) else None


register_detector(ADDRESSED, addressed, title="Asked by name")
