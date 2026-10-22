"""Every theme, one file each, crossed with the two modes: one
Tailwind/DaisyUI token source, every generated theme at parity."""

from pathlib import Path
import re
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.components.frontend.dashboard.modals.modal_sections.chart_primitives import (
    ChartColors,
)
from app.components.web_frontend.rendering import templates
from app.components.web_frontend.themes import (
    THEMES_DIR,
    Theme,
    Typeface,
    theme_named,
    themes,
)
from app.core.config import settings
from tests.web.dom import one, select
from tests.web.node import run

WEB = Path("app/components/web_frontend")
INPUT_CSS = WEB / "static/input.css"
TAILWIND = Path("tailwind.config.js")
MODES = ("dark", "light")
THEMES = tuple(f"{name}-{mode}" for name in themes() for mode in MODES)

HEX = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b(?![\w-])")
# Classes that name a literal color rather than a token; they look right
# on the dark theme and wrong on the light one.
THEME_BLIND = re.compile(
    r"\b(?:[\w-]+:)?(?:text|bg|border|ring|divide)-(?:white|black|gray-\d+|red-\d+)\b"
)


# An ``aegis-*`` color as a utility names it: text-aegis-teal, bg-aegis-card/60.
AEGIS_COLOR = re.compile(
    r"\b(?:text|bg|border|ring|divide|fill|stroke|outline|from|via|to)-aegis-([a-z]+)\b"
)


def tailwind(path: str) -> Any:
    """``path`` of the Tailwind config (``.daisyui.themes``), with DaisyUI
    stubbed out: the config only names the plugin, it never calls it."""
    return run(
        "const M = require('module'); const load = M.prototype.require;"
        " M.prototype.require = function (id) {"
        " return id === 'daisyui' ? {} : load.apply(this, arguments); };"
        f" console.log(JSON.stringify(require('./tailwind.config.js'){path}))"
    )


def aegis_colors() -> set[str]:
    return set(tailwind(".theme.extend.colors.aegis"))


def theme_config() -> dict[str, dict[str, str]]:
    return {
        name: body
        for entry in tailwind(".daisyui.themes")
        for name, body in entry.items()
    }


class TestThemeFiles:
    def test_a_theme_is_its_file(self) -> None:
        assert set(themes()) == {p.stem for p in THEMES_DIR.glob("*.json")}
        assert {"aegis", "steward"} <= set(themes())
        assert theme_named("aegis").label == "Aegis"

    def test_a_theme_that_is_not_there_names_the_ones_that_are(self) -> None:
        with pytest.raises(ValueError, match="aegis"):
            theme_named("parchment")


class TestTokens:
    def test_all_generated_themes_share_tokens(self) -> None:
        generated = theme_config()
        assert set(generated) == set(THEMES)
        assert len({frozenset(body) for body in generated.values()}) == 1
        for body in generated.values():
            chart = [key for key in body if key.startswith("--aegis-chart-")]
            assert len(chart) == len(ChartColors.RAMP)
            assert body["--aegis-font-body"] and body["--aegis-font-display"]
        assert (
            generated["aegis-dark"]["--rounded-box"]
            != generated["steward-dark"]["--rounded-box"]
        )

    def test_tailwind_colors_read_daisyui_variables(self) -> None:
        config = TAILWIND.read_text()
        assert (
            "const daisy = (name) => `oklch(var(--${name}) / <alpha-value>)`" in config
        )
        for name in ("bg", "card", "border", "text", "muted", "teal", "amber", "error"):
            assert re.search(rf'{name}: daisy\("[\w-]+"\)', config), name
        assert "[data-theme" not in INPUT_CSS.read_text()

    def test_every_aegis_color_in_use_is_defined(self) -> None:
        """An undefined one renders nothing in a template and fails the CSS
        build in an ``@apply``: ``aegis-accent`` did both, unnoticed until a
        page used the scheduler clock."""
        sources = [INPUT_CSS, *WEB.joinpath("templates").rglob("*.html")]
        used = {
            name for path in sources for name in AEGIS_COLOR.findall(path.read_text())
        }
        assert used - aegis_colors() == set()

    def test_shape_and_voice_tokens(self) -> None:
        config = TAILWIND.read_text()
        assert 'DEFAULT: "var(--rounded-btn)"' in config
        assert 'lg: "var(--rounded-box)"' in config
        assert 'display: "var(--aegis-font-display)"' in config
        css = INPUT_CSS.read_text()
        assert "font-size: var(--aegis-scale)" in css
        assert "font-family: var(--aegis-font-body)" in css
        assert "var(--aegis-label-case)" in css


class TestNoLiterals:
    @pytest.mark.parametrize(
        "path",
        sorted(p for p in WEB.rglob("*.html"))
        + sorted((WEB / "static/js").glob("*.js")),
        ids=lambda p: str(p.relative_to(WEB)),
    )
    def test_no_hex_outside_the_token_definitions(self, path: Path) -> None:
        source = path.read_text()
        # id selectors (#app-content) share the sigil; strip them first.
        source = re.sub(r"#[a-z][\w-]*[g-z_-][\w-]*", "", source)
        assert not HEX.search(source), HEX.search(source)

    @pytest.mark.parametrize(
        "path",
        sorted(WEB.rglob("*.html")),
        ids=lambda p: str(p.relative_to(WEB)),
    )
    def test_no_theme_blind_color_classes(self, path: Path) -> None:
        found = THEME_BLIND.findall(path.read_text())
        assert not found, found


class TestSwitching:
    def test_theme_script_runs_before_first_paint(self, client: TestClient) -> None:
        """A sync script in <head>, ahead of the stylesheet, applies the
        stored theme so a light-theme user never sees a dark flash."""
        page = client.get("/").text
        head = one(page, "head")
        srcs = [
            (el.tag, el.get("src") or el.get("href") or "")
            for el in select(head, "script[src], link[rel=stylesheet]")
        ]
        theme = next(i for i, (_, s) in enumerate(srcs) if "js/theme" in s)
        stylesheet = next(i for i, (tag, _) in enumerate(srcs) if tag == "link")
        assert theme < stylesheet
        assert one(head, 'script[src*="js/theme"]').get("defer") is None

    def test_html_carries_the_default_theme(self, client: TestClient) -> None:
        page = client.get("/").text
        assert one(page, "html").get("data-theme") == f"{settings.WEB_THEME}-dark"
        script = one(page, 'script[src*="js/theme"]')
        assert script.get("data-theme") == settings.WEB_THEME
        assert script.get("data-themes").split() == list(themes())
        assert script.get("data-fixed") is None, "the Overseer's viewer may switch"

    def test_navbar_offers_every_theme(self, client: TestClient) -> None:
        page = client.get("/").text
        assert one(page, "summary[data-theme-toggle]").get("aria-label")
        offered = [b.get("data-set-theme") for b in select(page, "[data-set-theme]")]
        assert offered == list(themes())

    def test_a_layout_may_fix_its_theme_and_load_its_type(self) -> None:
        """A public site wears its own theme whatever the viewer chose on
        the Overseer, and its faces load before the stylesheet."""
        serif = Theme(
            name="parchment",
            shape={},
            type=Typeface(
                display="serif", body="serif", fonts="https://fonts.test/css2"
            ),
        )
        head = templates.env.from_string(
            '{% from "components/macros/layout.html" import appearance_head %}'
            "{{ appearance_head(theme, fixed=true) }}"
        ).render(theme=serif)
        script = one(head, 'script[src*="js/theme"]')
        assert (script.get("data-theme"), script.get("data-fixed")) == ("parchment", "")
        fonts = one(head, "link[data-theme-fonts]")
        assert fonts.get("href") == "https://fonts.test/css2"
        order = [
            el.get("src") or el.get("href")
            for el in select(head, "script[src], link[rel=stylesheet]")
        ]
        assert [("theme" in u, "fonts" in u, "app" in u) for u in order] == [
            (True, False, False),
            (False, True, False),
            (False, False, True),
        ], order
