"""Chrome for the guided setup: styles, primitives, and display helpers.

Shared vocabulary for every guided screen — the palette, the raw-key reader,
the ``guided.*`` translation shim, docs-line rendering, and the ``_Choice``
row the selectors and pages both render. Extracted so the screen modules
(:mod:`aegis.cli.guided`, :mod:`aegis.cli.guided_blueprints`) can each import
one vocabulary instead of importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from ..constants import DOCS_BASE_URL
from ..core.plugins.spec import PluginSpec
from ..i18n import t
from .brand import AEGIS_TEAL

ACCENT = AEGIS_TEAL
MUTED = "grey42"
BODY = "grey74"
LABEL = "grey50"
RULE_STYLE = "grey23"
REQUIRES = AEGIS_TEAL  # hard-dependency names on the Requires line

MIN_WIDTH = 60
MIN_HEIGHT = 20
SIDEBAR_WIDTH = 26

_ARROWS = {
    b"[A": "up",
    b"[B": "down",
    b"[C": "right",
    b"[D": "left",
    b"OA": "up",
    b"OB": "down",
    b"OC": "right",
    b"OD": "left",
}


def _read_key(fd: int) -> str:
    """One keypress from a raw fd; handles CSI/SS3 arrows and bare ESC."""
    import os
    import select

    ch = os.read(fd, 1)
    if ch == b"\x1b":
        if not select.select([fd], [], [], 0.05)[0]:
            return "esc"
        return _ARROWS.get(os.read(fd, 2), "esc")
    return ch.decode("utf-8", "ignore")


# Capability-first display overrides: the guided setup presents what a
# building block DOES; the underlying component name (redis, ai) is
# unchanged everywhere else (specs, engine, quick mode, bracket syntax).
_DISPLAY_NAMES = {
    "ai": "AI",
    "redis": "Cache/Broker/Pubsub",
}


def _display_name(name: str) -> str:
    """Terminal display form of a component/service name."""
    return _g(f"display.{name}", _DISPLAY_NAMES.get(name, name.capitalize()))


def _g(key: str, default: str, **kwargs: object) -> str:
    """Translate a guided-chrome string, falling back to the inline default.

    Keys live under ``guided.*`` and are OPTIONAL in the locale files:
    ``t`` returns the key on a miss and the English default is used
    instead, so locales can adopt guided strings incrementally (the
    translator adds ``guided.*`` keys to en + a locale together) without
    tripping the locale-completeness tests today.
    """
    full_key = f"guided.{key}"
    result = t(full_key, **kwargs)
    if result == full_key:
        return default.format(**kwargs) if kwargs else default
    return result


def _docs_url(spec: PluginSpec) -> str | None:
    """Documentation page URL for a spec, or None when it has no page.

    Rendered as a VISIBLE plain URL (the terminal auto-linkifies it), not
    an OSC 8 styled hyperlink — same pattern as the post-init "Docs:" line.
    Styled links proved unreliable across terminals.
    """
    if not spec.docs_path:
        return None
    return f"{DOCS_BASE_URL}{spec.docs_path}/"


# The postgres provider screen offers Neon by name, so it links the page
# that explains it. Not a spec ``docs_path``: providers are choices inside
# the database component, not plugins with pages of their own.
_NEON_DOCS_URL = f"{DOCS_BASE_URL}components/database/neon/"


def _fit_url(url: str, width: int) -> str:
    """The deepest ancestor of ``url`` that fits in ``width`` cells.

    Terminals without OSC 8 only linkify what they can SEE, so every form
    this returns must be a complete, valid URL — scheme included, no
    ellipsis, never wrapped. mkdocs directory-URLs make every ancestor of
    a docs page a real page, so a narrow terminal degrades to a working
    link one level up rather than a broken or dead one. Measures with
    ``cell_len`` (URLs are ASCII today, but the contract is cells). The
    origin is the floor: callers must give it at least that much room.
    """
    if cell_len(url) <= width:
        return url
    scheme, _, rest = url.partition("://")
    host, _, path = rest.partition("/")
    origin = f"{scheme}://{host}/"
    segments = [s for s in path.split("/") if s]
    while segments:
        candidate = f"{origin}{'/'.join(segments)}/"
        if cell_len(candidate) <= width:
            return candidate
        segments.pop()
    return origin


def _docs_line(url: str, width: int) -> Text:
    """One-line plain-text URL the terminal's own detection can linkify.

    NO OSC 8 hyperlink, ever: terminals that see one suppress their own
    URL detection for that region, and terminals that don't render OSC 8
    then show no link at all — plain text is the only mechanism that
    proved reliable across terminals. ``_fit_url`` keeps the visible text
    a complete, valid URL at any width so detection always has a working
    target.
    """
    return Text(_fit_url(url, width), style=MUTED, justify="center", no_wrap=True)


def _one_datastore_note() -> str:
    """Shown on every screen whose engine pick doubles as the project default.

    Picking postgres for the scheduler (or AI storage, or the database
    itself) fixes the ONE datastore every later question reuses — the user
    must learn that here, not when the AI storage screen silently skips.
    """
    return _g(
        "note.one_datastore",
        "One datastore per project: choosing an engine here sets the "
        "project database, shared by anything else that stores data.",
    )


def _spec_blurb(spec: PluginSpec) -> str:
    """Localizable editorial paragraph for a spec.

    Looks for ``component.<name>.long`` / ``service.<name>.long`` in the
    locale files; falls back to the packaged ``long_description`` (then the
    one-line ``description``).
    """
    kind = getattr(spec.kind, "value", "component")
    key = f"{kind}.{spec.name}.long"
    result = t(key)
    if result != key:
        return result
    return spec.long_description or spec.description


class _GoBack(Exception):  # noqa: N818 — control-flow signal, not an error
    """Raised by the live select loop when the user presses esc."""


@dataclass
class _Choice:
    value: str
    title: str
    body: str = ""
    # Docs page for THIS choice; rendered only while the choice is focused.
    docs_url: str = ""
