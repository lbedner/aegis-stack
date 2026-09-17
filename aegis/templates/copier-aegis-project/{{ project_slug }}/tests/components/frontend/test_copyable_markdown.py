"""Read-only markdown in the dashboard can be copied.

Schemas and migration bodies render as fenced code in a Flet markdown
control, and selecting text inside one is fiddly to impossible. The
thing a reader wants is the CREATE TABLE statement or the migration
body, so the copy has to hand over the RAW source, not the fenced
markdown that was built to display it.

One control owns that, so no modal grows its own copy logic.
"""

from __future__ import annotations

import flet as ft
import pytest

from app.components.frontend.controls.markdown import copyable_markdown


def _find(control: ft.Control, kind: type) -> list[ft.Control]:
    """Every descendant of a given type, depth first."""
    found: list[ft.Control] = []
    if isinstance(control, kind):
        found.append(control)
    for attr in ("controls", "content"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        for item in child if isinstance(child, list) else [child]:
            if isinstance(item, ft.Control):
                found.extend(_find(item, kind))
    return found


class FakePage:
    """Enough page for the copy handler."""

    def __init__(self) -> None:
        self.clipboard: str | None = None
        self.opened: list[object] = []

    def set_clipboard(self, value: str) -> None:
        self.clipboard = value

    def open(self, control: object) -> None:
        self.opened.append(control)

    def update(self) -> None:
        pass


class FakeEvent:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.control = None


SCHEMA = "CREATE TABLE user (\n    id INTEGER NOT NULL\n);"
RENDERED = f"```sql\n{SCHEMA}\n```"


class TestWhatGetsCopied:
    def test_the_clipboard_receives_the_raw_source(self) -> None:
        """Not the fences. Pasting ```sql into a SQL client is useless."""
        page = FakePage()
        control = copyable_markdown(RENDERED, copy_text=SCHEMA)

        button = _find(control, ft.IconButton)[0]
        button.on_click(FakeEvent(page))

        assert page.clipboard == SCHEMA
        assert "```" not in (page.clipboard or "")

    def test_copying_confirms_it_happened(self) -> None:
        """A copy button with no feedback leaves you pressing it twice."""
        page = FakePage()
        control = copyable_markdown(RENDERED, copy_text=SCHEMA)

        _find(control, ft.IconButton)[0].on_click(FakeEvent(page))

        assert page.opened, "clicking copy gave no feedback"

    def test_the_markdown_still_renders_the_fenced_body(self) -> None:
        """The display value and the copied value are different strings,
        which is the whole point; neither may leak into the other."""
        control = copyable_markdown(RENDERED, copy_text=SCHEMA)

        markdown = _find(control, ft.Markdown)
        assert len(markdown) == 1
        assert markdown[0].value == RENDERED

    def test_copy_text_defaults_to_the_rendered_value(self) -> None:
        """For bodies that are already plain markdown, there is nothing
        to strip and the caller should not have to say so twice."""
        page = FakePage()
        control = copyable_markdown("# Just markdown")

        _find(control, ft.IconButton)[0].on_click(FakeEvent(page))

        assert page.clipboard == "# Just markdown"


class TestItStaysAMarkdownControl:
    @pytest.mark.parametrize("dark", [True, False])
    def test_it_is_themed_in_both_modes(self, dark: bool) -> None:
        """The dashboard renders in either mode and the code theme has
        to follow, exactly as the bare control did."""
        control = copyable_markdown(RENDERED, copy_text=SCHEMA, dark=dark)

        markdown = _find(control, ft.Markdown)[0]
        assert markdown.code_theme is not None
        assert markdown.md_style_sheet is not None

    def test_it_is_still_selectable(self) -> None:
        """Copy is an addition, not a replacement: selecting a single
        line has to keep working."""
        control = copyable_markdown(RENDERED, copy_text=SCHEMA)

        assert _find(control, ft.Markdown)[0].selectable is True
