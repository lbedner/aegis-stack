"""Theming: a theme is a block of CSS variables, nothing else.

Every color a template or script uses is a token defined per
``[data-theme]`` in ``input.css``; Tailwind's ``aegis.*`` names map onto
those tokens. These tests keep the single rebrand point single.
"""

from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from tests.web.dom import one, select

WEB = Path("app/components/web_frontend")
INPUT_CSS = WEB / "static/input.css"
TAILWIND = Path("tailwind.config.js")
THEMES = ("aegis", "aegis-light")

HEX = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b(?![\w-])")
# Classes that name a literal color rather than a token; they look right
# on the dark theme and wrong on the light one.
THEME_BLIND = re.compile(
    r"\b(?:[\w-]+:)?(?:text|bg|border|ring|divide)-(?:white|black|gray-\d+|red-\d+)\b"
)


def theme_blocks(css: str) -> dict[str, set[str]]:
    """Token names declared inside each ``[data-theme="..."]`` block."""
    blocks: dict[str, set[str]] = {}
    for match in re.finditer(r'\[data-theme="([\w-]+)"\][^{]*\{([^}]*)\}', css):
        names = set(re.findall(r"--aegis-[\w-]+", match.group(2)))
        blocks[match.group(1)] = blocks.get(match.group(1), set()) | names
    return blocks


class TestTokens:
    def test_both_themes_define_the_same_tokens(self) -> None:
        blocks = theme_blocks(INPUT_CSS.read_text())
        assert set(blocks) >= set(THEMES)
        assert blocks["aegis"] == blocks["aegis-light"]
        assert {"--aegis-bg", "--aegis-card", "--aegis-text", "--aegis-teal"} <= blocks[
            "aegis"
        ]

    def test_chart_ramp_is_a_token_set(self) -> None:
        blocks = theme_blocks(INPUT_CSS.read_text())
        ramp = {name for name in blocks["aegis"] if name.startswith("--aegis-chart-")}
        assert len(ramp) >= 8

    def test_tailwind_colors_reference_the_tokens(self) -> None:
        """``bg-aegis-card`` and friends keep working; only the values move."""
        config = TAILWIND.read_text()
        assert "rgb(var(--aegis-${name}) / <alpha-value>)" in config
        for name in ("bg", "card", "border", "text", "muted", "teal", "amber", "error"):
            assert f'{name}: token("{name}")' in config, name

    def test_daisyui_ships_both_themes(self) -> None:
        config = TAILWIND.read_text()
        for theme in THEMES:
            assert re.search(rf'["\']?{theme}["\']?\s*:\s*\{{', config), theme


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
        assert one(client.get("/").text, "html").get("data-theme") == "aegis"

    def test_navbar_has_a_theme_toggle(self, client: TestClient) -> None:
        toggle = one(
            client.get("/").text, "button[data-theme-toggle]"
        )
        assert toggle.get("aria-label")
