"""Reusable read-only detail popup.

A record-agnostic dialog: pass a title and grouped ``(label, value)`` sections
and it renders a clean, scrollable key/value view. Callers (transactions,
trades, anything) supply their own field mapping, so the dialog itself stays
generic — one component for every "click a row, see everything" surface.
"""

from __future__ import annotations

from typing import NamedTuple

import flet as ft

from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.tag import Tag
from app.components.frontend.controls.text import (
    BodyText,
    H3Text,
    NumericText,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

# (label, value) — value is pre-formatted by the caller. Empty/None values are
# dropped so a record only shows the fields it actually has.
DetailField = tuple[str, str | None]
DetailSection = tuple[str, list[DetailField]]


class HeroSpec(NamedTuple):
    """The record's own identity, promoted above the generic field list -
    what a transaction actually IS (who, how much, when) rather than the
    first row of its data model. ``chip_text`` is optional (e.g. no
    category yet); everything else is required, since a record with
    nothing to headline shouldn't be using the hero at all.
    """

    primary: str
    meta: str
    amount_text: str
    amount_color: str
    chip_text: str | None = None


_LABEL_WIDTH = 160


def _field_row(label: str, value: str | None, *, label_width: int) -> ft.Control:
    return ft.Row(
        [
            ft.Container(content=SecondaryText(label), width=label_width),
            ft.Container(content=BodyText(str(value), selectable=True), expand=True),
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=Theme.Spacing.MD,
    )


def build_field_blocks(
    sections: list[DetailSection],
    *,
    collapsed_sections: frozenset[str] = frozenset(),
    label_width: int = _LABEL_WIDTH,
) -> list[ft.Control]:
    """Section headers + field rows from grouped ``(label, value)`` data -
    the part of a detail view that isn't the hero. Shared by
    ``RecordDetailDialog`` (wrapped in dialog chrome, hero on top) and
    ``DataTable``'s inline row-expand (embedded directly under the row,
    no hero - the row's own cells already show the record's identity).
    """
    blocks: list[ft.Control] = []
    for section_title, fields in sections:
        rows = [
            _field_row(label, value, label_width=label_width)
            for label, value in fields
            if value not in (None, "")
        ]
        if not rows:
            continue
        if section_title and section_title in collapsed_sections:
            blocks.append(
                ft.Container(
                    content=_CollapsibleSection(section_title, rows),
                    padding=ft.padding.only(top=Theme.Spacing.SM),
                )
            )
            continue
        if section_title:
            blocks.append(
                ft.Container(
                    # size override, not H3Text's own default: this
                    # dialog's OWN title (StyledAlertDialog's title=) is
                    # ALSO H3Text, so at the same size a section header
                    # inside the dialog read as equal to (or, given it's
                    # bold at a shorter length, arguably louder than) the
                    # dialog's own title - no visual hierarchy between the
                    # two. BODY_LARGE keeps H3Text's semibold weight/color
                    # (still a clear step up from the BODY-sized field
                    # rows below it) while landing under the title's H3
                    # size.
                    content=H3Text(section_title, size=Theme.Typography.BODY_LARGE),
                    padding=ft.padding.only(top=Theme.Spacing.SM),
                )
            )
        blocks.extend(rows)
    return blocks


class _CollapsibleSection(ft.Column):
    """A section header that hides its own rows until clicked - for fields
    a viewer only occasionally needs (import/reconciliation metadata),
    so they don't compete for attention with the fields that answer "what
    IS this record" every single time the dialog opens.
    """

    def __init__(self, title: str, rows: list[ft.Control]) -> None:
        super().__init__(spacing=Theme.Spacing.XS, tight=True)
        self._expanded = False
        self._icon = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_RIGHT,
            size=16,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self._rows_column = ft.Column(
            rows, spacing=Theme.Spacing.XS, visible=False, tight=True
        )
        header = ft.Container(
            content=ft.Row(
                [
                    self._icon,
                    SecondaryText(
                        title,
                        size=Theme.Typography.BODY_SMALL,
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            on_click=self._toggle,
            ink=True,
            border_radius=4,
            padding=ft.padding.symmetric(vertical=2),
        )
        self.controls = [header, self._rows_column]

    def _toggle(self, _e: ft.ControlEvent) -> None:
        self._expanded = not self._expanded
        self._rows_column.visible = self._expanded
        self._icon.name = (
            ft.Icons.KEYBOARD_ARROW_DOWN
            if self._expanded
            else ft.Icons.KEYBOARD_ARROW_RIGHT
        )
        if self.page:
            self.update()


class RecordDetailDialog(StyledAlertDialog):
    """A titled, scrollable label/value detail dialog. ``show()`` opens it."""

    def __init__(
        self,
        page: ft.Page,
        title: str,
        sections: list[DetailSection],
        *,
        subtitle: str | None = None,
        hero: HeroSpec | None = None,
        collapsed_sections: frozenset[str] = frozenset(),
    ) -> None:
        """
        Args:
            hero: The record's identity, promoted above the generic
                section list (payee + amount, chip for its category) -
                see ``HeroSpec``. Optional: a record with no natural
                "headline" (a trade, say) can skip it and fall back to
                the plain title-only look this dialog always had.
            collapsed_sections: Section titles (matching ``sections``)
                that start hidden behind a click instead of always shown
                - for metadata a viewer only occasionally wants (import
                source, dedup status), not the fields that answer what
                the record actually is.
        """
        self._page = page
        blocks: list[ft.Control] = []
        if hero is not None:
            blocks.append(self._hero_block(hero))
        if subtitle:
            blocks.append(SecondaryText(subtitle))
        blocks.extend(
            build_field_blocks(sections, collapsed_sections=collapsed_sections)
        )
        super().__init__(
            title=title,
            # Inside the panel Column the scroll region needs an explicit
            # height bound (an unbounded Column child never scrolls, it
            # overflows) - size to the rows, capped so deep records scroll.
            body=ft.Container(
                content=ft.Column(
                    blocks,
                    spacing=Theme.Spacing.XS,
                    scroll=ft.ScrollMode.AUTO,
                    tight=True,
                ),
                height=min(520, 40 + 28 * len(blocks)),
            ),
            # × in the title row, not a footer "Close" button - a
            # read-only dialog's only "action" is dismissing it, and a
            # footer button for that reads as a separate decision rather
            # than the obvious way out. Teal accent bar for the same
            # reason the hero exists: a flat 1px OUTLINE panel on the
            # page's near-black background had no depth of its own.
            on_close=self._close,
            accent_color=Theme.Colors.ACCENT,
            width=600,
        )

    def _hero_block(self, hero: HeroSpec) -> ft.Control:
        rows: list[ft.Control] = [
            ft.Row(
                [
                    ft.Column(
                        [
                            PrimaryText(
                                hero.primary,
                                size=Theme.Typography.H3,
                                weight=ft.FontWeight.W_600,
                            ),
                            SecondaryText(hero.meta),
                        ],
                        spacing=2,
                        tight=True,
                    ),
                    ft.Container(expand=True),
                    NumericText(
                        hero.amount_text,
                        size=Theme.Typography.H2,
                        weight=ft.FontWeight.W_600,
                        color=hero.amount_color,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=Theme.Spacing.MD,
            )
        ]
        if hero.chip_text:
            rows.append(Tag(hero.chip_text, color=Theme.Colors.ACCENT))
        return ft.Column(rows, spacing=Theme.Spacing.SM, tight=True)

    async def _close(self) -> None:
        self.open = False
        self._page.update()

    def show(self) -> None:
        self._page.open(self)
