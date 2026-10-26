"""An answer as it should be said: the agent's words, without the markup.

The stack used to rewrite answers for speech with a second model call, run
as its own persisted conversation under ``system_voice_convert`` and outside
the agent that answered. That cost a model call per turn, wrote a history
nobody asked for, and could say something the agent had not. Markdown is
layout, not content, so it is stripped here instead.

How a term is said is one list for every voice, each term once whatever
its case (``term_key``): the stack's own names (``DEFAULTS``), an app's own
over them (``register_pronunciation``), and the rows saved in the Voices
dialog over both (``use_saved``, loaded from the database where there is
one). Read aloud, the speech service says each term the list's way
(``pronounced``); a live call's model speaks for itself, so it is told the
list instead (``pronunciation_instructions``).
"""

from collections.abc import Iterable
import re

from pydantic import BaseModel

from app.core.figures import FIGURES

_FENCED = re.compile(r"```.*?```", re.DOTALL)
# Link text holds no "[" and a target no "(": each attempt then stops at the
# next bracket rather than scanning to the end, which made a run of "["
# quadratic (CodeQL py/polynomial-redos).
_LINK = re.compile(r"!?\[([^\[\]]*)\]\([^()]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~|`)")
# One class for the prefix: two \s* around an optional "|" could both match
# the same spaces, which went quadratic on a long run of them.
_TABLE_RULE = re.compile(r"^[\s|:]*-{2,}")
_ENDS_A_SENTENCE = (".", "!", "?", ":", ";")


def to_spoken(text: str, max_chars: int = 4096) -> str:
    """Plain sentences from markdown, cut at a sentence end within ``max_chars``."""
    text = _LINK.sub(r"\1", _FENCED.sub("", text))
    lines = []
    for raw in text.splitlines():
        if _TABLE_RULE.match(raw):
            continue
        line = _EMPHASIS.sub("", _BULLET.sub("", _HEADING.sub("", raw)))
        line = " ".join(line.replace("|", " ").split())
        if line:
            lines.append(line)
    spoken = " ".join(
        line
        if index == len(lines) - 1 or line.endswith(_ENDS_A_SENTENCE)
        else f"{line}."
        for index, line in enumerate(lines)
    )
    if len(spoken) <= max_chars:
        return spoken
    cut = spoken[:max_chars]
    end = max(cut.rfind(mark + " ") for mark in ".!?")
    return cut[: end + 1] if end > max_chars // 2 else cut.rstrip() + "..."


class Pronunciation(BaseModel):
    """How one term is said: ``say`` as plain spelling any voice reads, and
    ``ipa`` kept for a provider's own dictionary (none reads it yet)."""

    model_config = FIGURES

    term: str
    say: str
    ipa: str | None = None

    @property
    def key(self) -> str:
        return term_key(self.term)


def term_key(term: str) -> str:
    """The one spelling a term is known by, whatever its case."""
    return term.strip().lower()


DEFAULTS = tuple(
    Pronunciation(term=term, say=say)
    for term, say in (
        ("Traefik", "traffic"),
        ("Redis", "red-iss"),
        ("PostgreSQL", "post-gres-Q-L"),
        ("SQLite", "S-Q-lite"),
        ("htmx", "H-T-M-X"),
        ("Pydantic", "pie-dantic"),
        ("Ollama", "oh-llama"),
        ("uvicorn", "you-vee-corn"),
        ("Aegis", "ee-jis"),
        ("MCP", "M-C-P"),
        ("OTel", "oh-tel"),
    )
)
_registered: dict[str, Pronunciation] = {}
_saved: dict[str, Pronunciation] = {}


def register_pronunciation(
    term: str, say: str, ipa: str | None = None, *, replace: bool = False
) -> None:
    """Add an app's own term to the list. Raises ValueError on a term
    already registered unless ``replace=True``, so two modules can't
    silently fight over one."""
    said = Pronunciation(term=term, say=say, ipa=ipa)
    if not replace and said.key in _registered:
        claimed = _registered[said.key].term
        raise ValueError(f"Pronunciation of {claimed!r} is already registered")
    _registered[said.key] = said


def use_saved(rows: Iterable[Pronunciation]) -> None:
    """The Voices dialog's rows, from the next thing said."""
    _saved.clear()
    _saved.update((row.key, row) for row in rows)


def saved_keys() -> frozenset[str]:
    """The terms a saved row says, which removing it gives back."""
    return frozenset(_saved)


def _by_key() -> dict[str, Pronunciation]:
    return {p.key: p for p in DEFAULTS} | _registered | _saved


def pronunciation_list() -> list[Pronunciation]:
    """The whole list, by term."""
    found = _by_key()
    return [found[key] for key in sorted(found)]


def pronounced(text: str) -> str:
    """``text`` with each listed term, as a whole word in any case, said
    the list's way. A match whose case does not fold back to its term (a
    dotted capital I) is left as written."""
    found = _by_key()
    terms = sorted(found, key=len, reverse=True)
    pattern = r"(?<!\w)(?:" + "|".join(map(re.escape, terms)) + r")(?!\w)"

    def said(match: re.Match[str]) -> str:
        known = found.get(term_key(match.group()))
        return known.say if known else match.group()

    return re.sub(pattern, said, text, flags=re.I)


def pronunciation_instructions() -> str:
    """The list as a live call's model is told it."""
    lines = [f'- Say "{p.term}" as "{p.say}".' for p in pronunciation_list()]
    return "Pronunciation (say these terms this way):\n" + "\n".join(lines)
