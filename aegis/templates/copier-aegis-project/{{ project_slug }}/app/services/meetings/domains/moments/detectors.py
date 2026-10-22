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

from app.core.discovery import import_modules_named

# The module another service registers its detectors and actions in.
EXTENSIONS = "meeting_moments"


@dataclass(frozen=True)
class Heard:
    """One line as a detector reads it: who said it, whether that is the
    owner, and what was said so far."""

    line_id: int
    speaker: str
    text: str
    is_me: bool


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


def question(heard: Heard) -> str | None:
    """A question someone other than the owner asks: their line ending in
    a question mark."""
    text = heard.text.strip()
    return text if not heard.is_me and text.endswith("?") else None


register_detector("question", question, title="Questions")
