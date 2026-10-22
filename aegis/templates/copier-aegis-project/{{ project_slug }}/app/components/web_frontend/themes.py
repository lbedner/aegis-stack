"""The themes a page may wear, read from ``themes/*.json``: the files
``tailwind.config.js`` generates the stylesheet from, so the page and
the stylesheet always agree on which themes exist (see
docs/components/web-frontend/styling.md)."""

from __future__ import annotations

from functools import cache
import json

from pydantic import BaseModel, ConfigDict

from app.components.web_frontend.assets import COMPONENT_DIR

THEMES_DIR = COMPONENT_DIR / "themes"


class Typeface(BaseModel):
    """A theme's type: a display face for titles, a body face for the
    rest, and the stylesheet that loads them (a Google Fonts URL, or a
    local one for self-hosted faces), or None for faces every system has."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    display: str
    body: str
    fonts: str | None = None


class Theme(BaseModel):
    """One theme file: named by the file, shaped and typed by it, tinting
    a mode's palette where it says so."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    shape: dict[str, str]
    type: Typeface
    tints: dict[str, dict[str, str]] = {}

    @property
    def label(self) -> str:
        return self.name.title()


@cache
def themes() -> dict[str, Theme]:
    """Every theme by name, in file order."""
    return {
        path.stem: Theme.model_validate(
            {"name": path.stem, **json.loads(path.read_text())}
        )
        for path in sorted(THEMES_DIR.glob("*.json"))
    }


def theme_named(name: str) -> Theme:
    """The theme called ``name``; a name no file has is an error that says
    which exist."""
    if theme := themes().get(name):
        return theme
    raise ValueError(f"no theme named {name!r}; the themes are: {', '.join(themes())}")
