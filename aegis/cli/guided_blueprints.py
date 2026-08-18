"""Blueprint screens for the guided setup: the starting point and the gallery.

Mixed into :class:`aegis.cli.guided.GuidedSelectionUI`, which supplies the
frame, the paint loop, and the key reader. Kept apart from the question
screens because these two pages precede the selection engine entirely: they
choose which answers the engine will be handed, and they are the only screens
whose roster grows with the blueprint package rather than with the registries.
"""

from __future__ import annotations

from collections.abc import Callable

import typer
from rich.align import Align
from rich.console import Console, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from ..blueprints import BLUEPRINTS, Blueprint
from .guided_chrome import (
    ACCENT,
    BODY,
    LABEL,
    MUTED,
    _Choice,
    _display_name,
    _g,
    _GoBack,
)


class BlueprintScreens:
    """The starting-point and gallery pages.

    Bare annotations, not stubs: they type the host class's members for the
    checker without creating attributes that could shadow the real ones.
    """

    _console: Console
    _key: Callable[[], str]
    _paint: Callable[[RenderableType], None]
    _content_width: Callable[..., int]
    _frame: Callable[..., RenderableType]

    def choose_blueprint(self) -> Blueprint | None:
        """Starting point: blank canvas, or pick from the blueprint gallery.

        Two doors first so the roster can grow to dozens without turning
        the opening screen into a wall. Returns the chosen blueprint, or
        None for a blank canvas. Precedes the answers journal (not an
        engine screen), so it is never replayed; esc raises
        :class:`_GoBack` for the caller to re-show the welcome page.
        """
        if not BLUEPRINTS:
            return None
        doors = [
            _Choice(
                "blank",
                _g("choice.blueprint.blank", "Blank canvas"),
                _g(
                    "choice.blueprint.blank_desc",
                    "Answer one question per component and service.",
                ),
            ),
            _Choice(
                "gallery",
                # Parenthetical count: reads correctly at one or at fifty,
                # unlike a sentence that would need plural handling.
                f"{_g('choice.blueprint.browse', 'Start from a blueprint')}"
                f" ({len(BLUEPRINTS)})",
                _g(
                    "choice.blueprint.browse_desc",
                    "A ready-made stack, built and running in one step.",
                ),
            ),
        ]
        cursor = 0
        while True:
            cursor = self._pick_row(
                _g("section.starting_point", "Starting point"),
                _g("prompt.blueprint", "Where do you want to begin?"),
                _g(
                    "note.blueprint",
                    "Nothing here is final: every stack grows later with 'aegis add'.",
                ),
                doors,
                cursor,
            )
            if doors[cursor].value == "blank":
                return None
            chosen = self._blueprint_gallery()
            if chosen is not None:
                return chosen
            # esc in the gallery: back to the doors, this one still focused.

    def _pick_row(
        self,
        section: str,
        prompt: str,
        note: str,
        choices: list[_Choice],
        cursor: int,
    ) -> int:
        """Vertical option list where each row carries its own description.

        The horizontal chip renderer (``_body``) is built for short answers;
        on these screens the description IS the choice, so rows stack in the
        core-stack page's editorial style. Returns the chosen index; esc
        raises :class:`_GoBack`.
        """
        hints = self._row_hints()
        while True:
            body = self._rows_body(section, prompt, note, choices, cursor)
            self._paint(self._frame(body, hints, sidebar=False))
            key = self._key()
            if key in ("q", "\x03"):
                raise typer.Abort()
            if key == "esc":
                raise _GoBack()
            if key in ("up", "k", "left", "h"):
                cursor = (cursor - 1) % len(choices)
            elif key in ("down", "j", "right", "l"):
                cursor = (cursor + 1) % len(choices)
            elif key in ("\r", "\n"):
                return cursor

    def _row_hints(self) -> Text:
        return Text.assemble(
            ("↑/↓", ACCENT),
            (f" {_g('hint.move', 'move')}    ", LABEL),
            ("enter", ACCENT),
            (f" {_g('hint.select', 'select')}    ", LABEL),
            ("esc", ACCENT),
            (f" {_g('hint.back', 'back')}    ", LABEL),
            ("q", ACCENT),
            (f" {_g('hint.quit', 'quit')}", LABEL),
        )

    def _rows_body(
        self,
        section: str,
        prompt: str,
        note: str,
        choices: list[_Choice],
        cursor: int,
    ) -> RenderableType:
        """Header chrome plus the option rows, centered as one block."""
        width = self._content_width(sidebar=False)
        grid = Table.grid(padding=(0, 0))
        grid.add_column(width=width)
        grid.add_row(Text(section.upper(), style=LABEL, justify="center"))
        grid.add_row(Text())
        grid.add_row(Text(prompt, style="bold", justify="center"))
        if note:
            grid.add_row(Text())
            grid.add_row(Text(note, style=LABEL, justify="center"))
        grid.add_row(Text())
        block = Table.grid(padding=(0, 0))
        # Rows carry a description and a contents line, so they get most of
        # the (sidebar-less) measure rather than the narrow prose column.
        block.add_column(width=min(width - 8, 68))
        for i, choice in enumerate(choices):
            if i:
                block.add_row(Text())
            block.add_row(self._row_title(choice.title, focused=i == cursor))
            block.add_row(
                Padding(
                    Text(choice.body, style=BODY if i == cursor else MUTED),
                    (0, 0, 0, 2),
                )
            )
            if choice.docs_url:
                # Reused as the contents line on gallery rows.
                block.add_row(
                    Padding(
                        Text(choice.docs_url, style=ACCENT if i == cursor else MUTED),
                        (0, 0, 0, 2),
                    )
                )
        grid.add_row(Align.center(block))
        return grid

    def _row_title(self, title: str, *, focused: bool) -> Text:
        out = Text()
        if focused:
            out.append("▸ ", style=ACCENT)
            out.append(title, style="reverse bold")
        else:
            out.append("  ")
            out.append(title, style=MUTED)
        return out

    # ----- blueprint gallery ----------------------------------------------
    def _blueprint_gallery(self) -> Blueprint | None:
        """The roster. Returns the picked blueprint, or None on esc."""
        roster = list(BLUEPRINTS.values())
        hints = self._row_hints()
        cursor = 0
        while True:
            height = self._console.size[1]
            self._paint(
                self._frame(
                    self._gallery_body(roster, cursor, height), hints, sidebar=False
                )
            )
            key = self._key()
            if key in ("q", "\x03"):
                raise typer.Abort()
            if key == "esc":
                return None
            if key in ("up", "k", "left", "h"):
                cursor = (cursor - 1) % len(roster)
            elif key in ("down", "j", "right", "l"):
                cursor = (cursor + 1) % len(roster)
            elif key in ("\r", "\n"):
                return roster[cursor]

    def _gallery_body(
        self, roster: list[Blueprint], cursor: int, height: int
    ) -> RenderableType:
        """Blueprint rows, windowed to the terminal height.

        Each row shows what the blueprint contains, so the stack is legible
        without selecting it. Long rosters scroll: the window follows the
        cursor and a counter says where you are.
        """
        per_row = 4  # title + description + contents + separator
        chrome = 8  # section, prompt, note, blanks, counter
        window = max(1, (height - chrome) // per_row)
        first = 0
        if len(roster) > window:
            # Keep the cursor inside the window, clamped at both ends.
            first = min(max(0, cursor - window // 2), len(roster) - window)
        visible = roster[first : first + window]
        choices = [
            _Choice(
                bp.slug,
                _g(f"blueprint.{bp.slug}.title", bp.title),
                _g(f"blueprint.{bp.slug}.desc", bp.description),
                docs_url=" · ".join(_display_name(n) for n in bp.contents),
            )
            for bp in visible
        ]
        note = (
            _g(
                "gallery.counter",
                "{shown} of {total}",
                shown=f"{first + 1}-{first + len(visible)}",
                total=len(roster),
            )
            if len(roster) > window
            else ""
        )
        return self._rows_body(
            _g("section.blueprints", "Blueprints"),
            _g("prompt.gallery", "Pick a stack to build"),
            note,
            choices,
            cursor - first,
        )
