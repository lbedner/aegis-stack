"""Aegis brand palette and semantic rendering helpers for CLI output.

Single source for the colors used by aegis CLI surfaces. The hex values
mirror the generated frontend theme
(``app/components/frontend/theme.py`` in the template) so the CLI and the
product it generates share one visual identity.

Call sites express intent, never colors: import this module and use the
semantic helpers (``brand.success(...)``, ``brand.warn(...)``,
``brand.error(...)``, ``brand.accent(...)``, ``brand.muted(...)``). The
palette is defined here exactly once; no per-command color constants.
"""

from typing import Any

import typer

AEGIS_TEAL = "#17CCBF"
"""Primary teal/cyan — the brand standard accent (and success state)."""

AEGIS_TEAL_DARK = "#248F87"
"""Darker teal — secondary accent."""

AEGIS_WARNING = "#F5A623"
"""Warning amber — matches the frontend theme's ``ACCENT_WARNING``."""

AEGIS_ERROR = "#E23E3E"
"""Error red — mirrors the theme's ``ACCENT_STOP``."""


def _rgb(hex_color: str) -> tuple[int, int, int]:
    """Hex color to the (r, g, b) tuple click/typer expects."""
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


_TEAL = _rgb(AEGIS_TEAL)
_WARNING = _rgb(AEGIS_WARNING)
_ERROR = _rgb(AEGIS_ERROR)


def success(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """Echo a success line in the brand teal."""
    typer.secho(message, fg=_TEAL, bold=bold or None, nl=nl, err=err)


def accent(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """Echo an accented line (headings, highlights) in the brand teal."""
    typer.secho(message, fg=_TEAL, bold=bold or None, nl=nl, err=err)


def warn(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """Echo a warning line in the brand amber."""
    typer.secho(message, fg=_WARNING, bold=bold or None, nl=nl, err=err)


def error(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """Echo an error line in the brand red."""
    typer.secho(message, fg=_ERROR, bold=bold or None, nl=nl, err=err)


def muted(
    message: str = "", *, bold: bool = False, nl: bool = True, err: bool = False
) -> None:
    """Echo a secondary/de-emphasized line (terminal dim)."""
    typer.secho(message, dim=True, bold=bold or None, nl=nl, err=err)


def accent_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` in the brand teal for inline composition."""
    return typer.style(text, fg=_TEAL, bold=bold or None)


def warn_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` in the brand amber for inline composition."""
    return typer.style(text, fg=_WARNING, bold=bold or None)


def experimental_label() -> str:
    """The one-word experimental marker, unstyled.

    Renderers that style text themselves (the Rich-based guided setup)
    take this and apply ``AEGIS_WARNING``; typer surfaces take
    :func:`experimental_badge`. One word, one key, two render paths.
    """
    from ..i18n import t

    return t("common.experimental")


def experimental_badge() -> str:
    """:func:`experimental_label` in the warning colour."""
    return warn_text(experimental_label())


def muted_text(text: str, *, bold: bool = False) -> str:
    """Style ``text`` de-emphasized (terminal dim) for inline composition."""
    return typer.style(text, dim=True, bold=bold or None)


def questionary_style() -> Any:
    """Brand style for questionary prompts.

    Replaces questionary's default orange (``#FF9D00``) answer/pointer/
    highlight tokens with the brand teal. Imported lazily so plain
    ``typer``-only surfaces don't pay for questionary at import time.
    """
    import questionary

    return questionary.Style(
        [
            ("qmark", f"fg:{AEGIS_TEAL} bold"),
            ("question", "bold"),
            ("answer", f"fg:{AEGIS_TEAL} bold"),
            ("pointer", f"fg:{AEGIS_TEAL} bold"),
            ("highlighted", f"fg:{AEGIS_TEAL} bold"),
            ("selected", f"fg:{AEGIS_TEAL}"),
            ("instruction", "fg:#7E8A9A"),
            ("disabled", "fg:#7E8A9A italic"),
        ]
    )


def apply_help_theme() -> None:
    """Theme Typer's rich ``--help`` output to the brand palette.

    One accent (teal) encodes exactly one meaning — "a token you can type":
    command names and flags. Prose (usage, descriptions, titles) stays
    neutral foreground; annotations and chrome (metavars, defaults, env-var
    hints, panel borders) go dim. Two colors, three brightnesses — color is
    wayfinding, not decoration. Call once before building the Typer app;
    ``rich_utils`` constants are global, so every help panel inherits it.
    """
    from typer import rich_utils

    typeable = f"bold {AEGIS_TEAL}"  # commands + flags: the tokens you run
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
