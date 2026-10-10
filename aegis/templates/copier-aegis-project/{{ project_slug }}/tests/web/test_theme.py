"""The four Steward-derived themes share one Tailwind/DaisyUI token source."""

from pathlib import Path
import re
from typing import Any

from fastapi.testclient import TestClient
import pytest

from tests.web.dom import one, select
from tests.web.node import run

WEB = Path("app/components/web_frontend")
INPUT_CSS = WEB / "static/input.css"
TAILWIND = Path("tailwind.config.js")
THEMES = ("aegis-dark", "aegis-light", "steward-dark", "steward-light")

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


class TestTokens:
    def test_all_theme_pairs_share_tokens(self) -> None:
        themes = theme_config()
        assert set(themes) == set(THEMES)
        assert len({frozenset(body) for body in themes.values()}) == 1
        for body in themes.values():
            assert len([key for key in body if key.startswith("--aegis-chart-")]) == 8
        assert (
            themes["aegis-dark"]["--rounded-box"]
            != themes["steward-dark"]["--rounded-box"]
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
        css = INPUT_CSS.read_text()
        assert "font-size: var(--aegis-scale)" in css
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
        assert one(client.get("/").text, "html").get("data-theme") == "aegis-dark"

    def test_navbar_has_a_theme_toggle(self, client: TestClient) -> None:
        toggle = one(client.get("/").text, "summary[data-theme-toggle]")
        assert toggle.get("aria-label")
