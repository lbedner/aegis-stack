"""Overseer follows light and dark mode the way htmx does (#629).

One palette (``app/core/palette.json``) feeds both frontends: the htmx
build reads it through ``tailwind.config.js``, and Flet builds both of its
colour schemes from it. Every colour a Flet control names is a role in
those schemes, so flipping ``page.theme_mode`` repaints every control; a
hex value or a Material swatch written into a control is one mode's
colour, wrong in the other.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import flet as ft
import pytest

from app.components.frontend.theme import AegisTheme
from app.components.frontend.theme_manager import MODE_KEY, ThemeManager
from app.core.appearance import PALETTE
from tests.components.frontend._fakes import FakePage, FakeStorage

FRONTEND = Path("app/components/frontend")
PALETTE_FILE = Path("app/core/palette.json")

# The roles a control names directly: the structural ones. The tones
# (PRIMARY, ERROR, TERTIARY for warning, SECONDARY for info) go through
# ``AegisTheme.Colors``, which says what they mean; each colour has one name.
ROLES = {
    "ON_PRIMARY", "ON_ERROR", "ON_SECONDARY", "ON_TERTIARY",
    "PRIMARY_CONTAINER", "ON_PRIMARY_CONTAINER",
    "SECONDARY_CONTAINER", "ON_SECONDARY_CONTAINER",
    "TERTIARY_CONTAINER", "ON_TERTIARY_CONTAINER",
    "ERROR_CONTAINER", "ON_ERROR_CONTAINER",
    "OUTLINE", "SURFACE", "ON_SURFACE", "SURFACE_TINT",
    "SURFACE_CONTAINER_HIGHEST", "ON_SURFACE_VARIANT", "INVERSE_SURFACE",
    "ON_INVERSE_SURFACE", "INVERSE_PRIMARY", "SHADOW", "SCRIM",
}  # fmt: skip
TONES = {"primary", "error", "tertiary", "secondary"}
HARD_COLOR = re.compile(
    r"""["']#[0-9A-Fa-f]{3,8}["']|\bft\.Colors\.(?!with_opacity\b|TRANSPARENT\b)(\w+)"""
)
# A third party's own mark keeps its own colour in either mode.
BRAND_MARKS = {
    FRONTEND / "dashboard/modals/llm_catalog_tab/featured.py",
    FRONTEND / "controls/provider_icon.py",
}


class TestOnePalette:
    def test_flet_reads_the_palette_file(self) -> None:
        assert json.loads(PALETTE_FILE.read_text()) == PALETTE

    @pytest.mark.parametrize("mode", ["dark", "light"])
    def test_scheme_is_built_from_the_mode(self, mode: str) -> None:
        tokens = PALETTE[mode]
        scheme = AegisTheme.build(mode).color_scheme
        assert scheme is not None
        assert scheme.primary == tokens["primary"]
        assert scheme.surface == tokens["base-200"]
        assert scheme.surface_variant == tokens["base-100"]
        assert scheme.on_surface == tokens["base-content"]
        assert scheme.on_surface_variant == tokens["neutral"]
        assert scheme.outline == tokens["base-300"]
        assert scheme.error == tokens["error"]
        assert scheme.tertiary == tokens["warning"]
        assert scheme.secondary == tokens["info"]

    def test_tailwind_reads_the_palette_file(self) -> None:
        tailwind = Path("tailwind.config.js")
        if not tailwind.exists():
            pytest.skip("no htmx frontend in this stack")
        config = tailwind.read_text()
        assert 'require("./app/core/palette.json")' in config
        assert not re.search(r"#[0-9A-Fa-f]{6}", config.split("const SHAPES")[0])


class TestTokensFollowTheMode:
    def test_tokens_are_tones_or_washes(self) -> None:
        """A token names a tone, or a wash of the text colour: never a
        second name for a role a control can name itself."""
        tokens = {
            name: value
            for name, value in vars(AegisTheme.Colors).items()
            if name.isupper() and isinstance(value, str)
        }
        assert tokens
        for name, value in tokens.items():
            if "," in value:  # with_opacity(..., role)
                assert value.split(",")[0].lower() == "onsurface", name
            else:
                assert value.lower() in TONES, name

    def test_no_control_hard_codes_a_colour(self) -> None:
        found = []
        for path in sorted(FRONTEND.rglob("*.py")):
            if path in BRAND_MARKS or path == FRONTEND / "theme.py":
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                for match in HARD_COLOR.finditer(line):
                    if match.group(1) in ROLES:
                        continue
                    found.append(f"{path}:{number}: {line.strip()}")
        assert found == []


def themed_page(stored: dict[str, Any], brightness: Any = None) -> Any:
    page: Any = FakePage()
    page.client_storage = FakeStorage(stored)
    page.platform_brightness = brightness or ft.Brightness.DARK
    return page


class TestStartingMode:
    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            (None, ft.ThemeMode.DARK),
            ("dark", ft.ThemeMode.DARK),
            ("light", ft.ThemeMode.LIGHT),
            ("system", ft.ThemeMode.SYSTEM),
            ("sepia", ft.ThemeMode.DARK),
        ],
    )
    async def test_opens_in_the_stored_mode(
        self, stored: str | None, expected: ft.ThemeMode
    ) -> None:
        page = themed_page({MODE_KEY: stored} if stored else {})
        await ThemeManager(page).initialize_themes()
        assert page.theme_mode == expected

    async def test_toggle_stores_the_choice(self) -> None:
        page = themed_page({MODE_KEY: "dark"})
        manager = ThemeManager(page)
        await manager.initialize_themes()
        await manager.toggle_theme()
        assert page.theme_mode == ft.ThemeMode.LIGHT
        assert page.client_storage.stored[MODE_KEY] == "light"

    async def test_toggle_from_system_flips_what_shows(self) -> None:
        page = themed_page({MODE_KEY: "system"}, brightness=ft.Brightness.LIGHT)
        manager = ThemeManager(page)
        await manager.initialize_themes()
        assert not manager.is_dark_mode
        await manager.toggle_theme()
        assert page.theme_mode == ft.ThemeMode.DARK
