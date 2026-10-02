"""Brand palette and semantic CLI rendering.

Color encodes ONE meaning, consistently — state on status screens, typeable
tokens on ``--help`` — and nothing else. Visual hierarchy comes from
*brightness*, not hue: neutral foreground for values and prose, dim for labels
and chrome, and a single accent (teal) for the thing that matters. Two colors,
three brightnesses. Color is wayfinding, not decoration.

The hex values mirror the frontend theme ACCENT (#17CCBF) so the CLI and the
app it drives share one identity. Call sites express intent
(``theme.good(...)``, ``theme.label(...)``) rather than raw colors, so the
palette is defined here exactly once. The constants are plain hex strings so
they also work directly in Rich markup (``f"[{theme.ACCENT}]...[/]"``) and Rich
table column styles (``style=theme.ACCENT``).
"""

from typing import Any, NoReturn

import typer

ACCENT = "#17CCBF"
"""Teal — healthy/good state, success, and emphasis (the one accent)."""

WARNING = "#F5A623"
"""Amber — a warning: degraded or attention-worthy, but not broken."""

ERROR = "#E23E3E"
"""Red — an error or failed state."""


def _rgb(hex_color: str) -> tuple[int, int, int]:
    """Hex color to the (r, g, b) tuple click/typer expects."""
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


_TEAL = _rgb(ACCENT)
_AMBER = _rgb(WARNING)
_RED = _rgb(ERROR)


# --- whole-line helpers (echo) --------------------------------------------
def good(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """A healthy / success state, in brand teal."""
    typer.secho(message, fg=_TEAL, bold=bold or None, nl=nl, err=err)


def warn(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """A warning (degraded but usable), in brand amber."""
    typer.secho(message, fg=_AMBER, bold=bold or None, nl=nl, err=err)


def bad(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """An error / failed state, in brand red."""
    typer.secho(message, fg=_RED, bold=bold or None, nl=nl, err=err)


def fail(message: str) -> NoReturn:
    """Say what went wrong, in brand red, and exit 1."""
    bad(f"✗ {message}")
    raise typer.Exit(1)


def accent(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """Emphasis or a token you can type, in brand teal."""
    typer.secho(message, fg=_TEAL, bold=bold or None, nl=nl, err=err)


def title(message: str = "", *, nl: bool = True, err: bool = False) -> None:
    """A screen or section heading: neutral foreground, bold (it's prose)."""
    typer.secho(message, bold=True, nl=nl, err=err)


def label(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """A field label, note, hint, or chrome line: dim."""
    typer.secho(message, dim=True, bold=bold or None, nl=nl, err=err)


# --- inline text helpers (compose "Label: value" on one line) -------------
def good_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` as a healthy/success token (teal) for composition."""
    return typer.style(text, fg=_TEAL, bold=bold or None)


def warn_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` as a warning token (amber) for composition."""
    return typer.style(text, fg=_AMBER, bold=bold or None)


def bad_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` as an error token (red) for composition."""
    return typer.style(text, fg=_RED, bold=bold or None)


def accent_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` as emphasis / a typeable token (teal) for composition."""
    return typer.style(text, fg=_TEAL, bold=bold or None)


def label_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` as a dim field label for composition."""
    return typer.style(text, dim=True, bold=bold or None)


def console() -> Any:
    """A Rich ``Console`` with the repr auto-highlighter disabled.

    Rich's default highlighter auto-colors numbers, quoted strings, slash
    paths, URLs, etc. — incidental color that fights the theme, where color
    must encode exactly one meaning. Disabling it keeps VALUES neutral;
    explicit theme markup (``[{theme.ACCENT}]``) and ``style=`` still render.
    Use this for every CLI Console so the palette stays intentional.
    """
    from rich.console import Console

    return Console(highlight=False)


def questionary_style() -> Any:
    """Brand style for questionary prompts (teal accent, dim metadata)."""
    import questionary

    return questionary.Style(
        [
            ("qmark", f"fg:{ACCENT} bold"),
            ("question", "bold"),
            ("answer", f"fg:{ACCENT} bold"),
            ("pointer", f"fg:{ACCENT} bold"),
            ("highlighted", f"fg:{ACCENT} bold"),
            ("selected", f"fg:{ACCENT}"),
            ("instruction", "fg:#7E8A9A"),
            ("disabled", "fg:#7E8A9A italic"),
        ]
    )


def apply_help_theme() -> None:
    """Theme Typer's rich ``--help`` output to the brand palette.

    One accent (teal) means exactly one thing — "a token you can type":
    command names and flags. Prose (usage, descriptions) stays neutral
    foreground; annotations and chrome (metavars, defaults, env-var hints,
    panel borders) go dim. Call once before building the Typer app;
    ``rich_utils`` constants are global, so every help panel inherits it.
    """
    from typer import rich_utils

    typeable = f"bold {ACCENT}"  # commands + flags: the tokens you run
    # setattr (not direct assignment) so the type checker doesn't narrow each
    # rich_utils.STYLE_* to the Literal of its packaged default and reject the
    # override. Values: teal = typeable, dim = annotations, "" = neutral prose.
    overrides = {
        "STYLE_COMMANDS_TABLE_FIRST_COLUMN": typeable,  # command names
        "STYLE_OPTION": typeable,  # --flags
        "STYLE_SWITCH": typeable,  # -h style switches
        "STYLE_NEGATIVE_OPTION": typeable,
        "STYLE_NEGATIVE_SWITCH": typeable,
        "STYLE_METAVAR": "dim",  # TEXT/INTEGER metavars are annotations
        "STYLE_OPTION_ENVVAR": "dim",  # [env var: ...] — drop the yellow
        "STYLE_USAGE": "",  # "Usage:" header — neutral prose, not yellow
        "STYLE_HELPTEXT": "",  # help body — neutral foreground, not dimmed
    }
    for _name, _value in overrides.items():
        setattr(rich_utils, _name, _value)
