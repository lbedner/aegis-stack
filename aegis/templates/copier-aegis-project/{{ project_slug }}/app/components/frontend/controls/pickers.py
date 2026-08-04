"""Anchored search-pickers (category, payee) and the triggers that open them.

A search box pinned above a live-filtered list, opened as a bordered popup
anchored near wherever it was summoned from - visually and mechanically the
same ``Dropdown``-based popup ``AccountFilterButton`` already uses
(finance_modal.py), just single-PICK instead of a persistent multi-toggle,
and opened from an arbitrary caller tap event rather than its own visible
trigger.

That last part is the one real difference from every other ``Dropdown``
subclass in this app: these cells live on table rows, and a table can have
hundreds of rows. Building one full picker (and so one ``page.overlay``
entry, per ``Dropdown``'s own mount model) PER ROW would mean hundreds of
invisible full-page backdrop Containers piling up in the overlay just from
rendering the table once. Instead a caller builds ONE shared instance and
calls ``open_for(ids, e)`` from each row's own tap handler - the picker
repositions itself at that tap event's coordinates (the same
``ContainerTapEvent`` contract ``Dropdown._toggle`` already expects) and
remembers which id(s) it's picking for.

``ids`` is always a list, even for a single row - a bulk "apply to the N
selected" trigger and an individual row's cell both open the SAME popup
through the SAME method, just with a longer list; there is no separate
bulk-only code path to keep in sync with the single one.
"""

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend import styles
from app.components.frontend.controls.buttons import (
    PULSE_BUTTON_COMPACT_HEIGHT,
    PULSE_BUTTON_COMPACT_PADDING,
    PULSE_BUTTON_COMPACT_RADIUS,
)
from app.components.frontend.controls.dropdown import Dropdown
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

_PANEL_MAX_HEIGHT = 560
_PANEL_WIDTH = 320
_COUNT_LABEL_HEIGHT = 20
# _PANEL_MAX_HEIGHT minus the fixed overhead around the row list: the
# Dropdown panel's own vertical padding (2x Theme.Spacing.SM), the count
# label row (fixed height even when empty - see its own Container below,
# same "reserve the space so nothing jumps" idea as the header's own
# progress-bar gap in finance_modal.py), the search field (FormTextField's
# compact height, 36), the divider (1), and this Column's own spacing
# between its 4 children (3x Theme.Spacing.SM). An EXPLICIT height here,
# not expand=True (tried first, reverted): a Container never clips or
# bounds its child just because it claims flex space, so the inner
# scroll=AUTO Column still needs a real fixed-height box to actually
# scroll within instead of overflowing past it.
_ROWS_HEIGHT = _PANEL_MAX_HEIGHT - (2 * 8 + _COUNT_LABEL_HEIGHT + 36 + 1 + 3 * 8)


class SearchPickerButton(Dropdown):
    """``on_pick(ids, key)`` fires once, then the popup closes - picking is
    a one-shot choice for whichever row(s) summoned it, not a persistent
    filter a user leaves open and keeps toggling (contrast
    ``AccountFilterButton``, which stays open across clicks).

    ``on_create``, when given, adds a "+ Create <typed text>" row whenever
    the search text matches no existing option exactly - so naming a new
    payee happens right where you discovered you needed one, instead of in
    a separate management screen.
    """

    def __init__(
        self,
        *,
        options: list[tuple[str, str]],
        on_pick: Callable[[list[int], str], None],
        hint: str,
        on_create: Callable[[list[int], str], None] | None = None,
    ) -> None:
        self._options = options
        self._on_pick = on_pick
        self._on_create = on_create
        self._active_ids: list[int] = []
        self._count_label = SecondaryText("", size=Theme.Typography.CAPTION)
        self._rows_column = ft.Column(spacing=0, tight=True, scroll=ft.ScrollMode.AUTO)
        self._search = FormTextField(
            label="",
            hint=hint,
            show_label=False,
            compact=True,
            autofocus=True,
            on_change=self._on_search,
        )
        panel = ft.Column(
            [
                ft.Container(
                    content=self._count_label,
                    height=_COUNT_LABEL_HEIGHT,
                    padding=ft.padding.symmetric(horizontal=Theme.Spacing.SM),
                ),
                ft.Container(
                    content=self._search,
                    padding=ft.padding.symmetric(horizontal=Theme.Spacing.SM),
                ),
                ft.Divider(height=1, color=Theme.Colors.BORDER_SUBTLE),
                ft.Container(content=self._rows_column, height=_ROWS_HEIGHT),
            ],
            spacing=Theme.Spacing.SM,
        )
        # No visible trigger of its own - every real open comes through
        # open_for(), positioned at the CALLER's tap event, not this.
        super().__init__(
            trigger=ft.Container(width=0, height=0),
            panel=panel,
            trigger_width=200,
            min_width=_PANEL_WIDTH,
            max_width=_PANEL_WIDTH,
            max_height=_PANEL_MAX_HEIGHT,
        )
        # AFTER super().__init__(): _render_rows touches ``_panel_frame``,
        # which the base class creates. Rendering first (the original
        # order) meant every construction ran before that attribute
        # existed - survivable only while the guard happened to swallow
        # the AttributeError, which is masking an ordering bug rather than
        # not having one. The panel above is built with an empty
        # _rows_column and filled here instead.
        self._render_rows("")

    def update_options(self, options: list[tuple[str, str]]) -> None:
        """Refresh the option list (e.g. once the caller's own fetch
        resolves, if this picker was built before that landed, or after
        creating a new one)."""
        self._options = options
        self._render_rows(self._search.value)

    def open_for(self, entity_ids: list[int], e: ft.ControlEvent) -> None:
        """Open anchored at ``e``'s own tap position, staged for
        ``entity_ids``. Force-closed first: ``Dropdown._toggle`` treats
        "already open" as a close request, and this picker is shared
        across rows - a second row's tap while the panel is still open
        for the first must reposition and reopen, not just close it.
        """
        self._active_ids = entity_ids
        # A single row's own identity is already visible in its cell -
        # only worth calling out when picking applies somewhere the user
        # can't otherwise see, i.e. a bulk pick.
        self._count_label.value = (
            f"Applying to {len(entity_ids)} selected" if len(entity_ids) > 1 else ""
        )
        self._search.value = ""
        self._render_rows("")
        self.close()
        self._toggle(e)  # type: ignore[arg-type]

    def _on_search(self, e: ft.ControlEvent) -> None:
        self._render_rows(e.control.value or "")

    def _row(self, label: str, on_click: Callable[[ft.ControlEvent], None], color: str):
        # XS, not SM: these lists can run to hundreds of entries (267
        # categories in testing) and search only narrows so far before the
        # first character is typed - a denser row shows more per screenful
        # without scrolling, which is most of the point of the popup over
        # the old cramped inline field.
        return ft.Container(
            content=ft.Text(label, size=13, color=color),
            on_click=on_click,
            ink=True,
            border_radius=Theme.Components.BUTTON_RADIUS,
            padding=ft.padding.symmetric(
                vertical=Theme.Spacing.XS, horizontal=Theme.Spacing.MD
            ),
        )

    def _render_rows(self, query: str) -> None:
        typed = query.strip()
        q = typed.casefold()
        matches = (
            [(k, t) for k, t in self._options if q in t.casefold()]
            if q
            else self._options
        )
        rows: list[ft.Control] = []
        if (
            self._on_create is not None
            and typed
            and not any(t.casefold() == q for _k, t in self._options)
        ):
            rows.append(
                self._row(
                    f'+ Create "{typed}"',
                    lambda _e, text=typed: self._create(text),
                    Theme.Colors.ACCENT,
                )
            )
        rows.extend(
            self._row(t, lambda _e, k=k: self._pick(k), ft.Colors.ON_SURFACE)
            for k, t in matches
        )
        if not rows:
            rows = [
                ft.Container(
                    content=ft.Text(
                        "No matches", size=13, color=Theme.Colors.TEXT_SECONDARY
                    ),
                    padding=ft.padding.symmetric(
                        vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
                    ),
                )
            ]
        self._rows_column.controls = rows
        # Update ``_panel_frame`` (the rows live inside it, and updating the
        # inner column silently no-ops before the overlay is attached), but
        # guard on THAT control's own page rather than any proxy for it:
        #
        # - ``self.page is not None`` is true while ``_panel_frame`` is
        #   still detached - this Dropdown gets a page from its own parent
        #   long before its overlay layer is appended.
        # - ``self._mounted_overlay`` is no better: ``Dropdown.did_mount``
        #   sets that flag BEFORE ``page.overlay.append(...)``, so it is a
        #   promise rather than a fact, and a caller that renders rows in
        #   that window (``update_categories`` right after the category
        #   fetch resolves) crashed with "Container Control must be added
        #   to the page first".
        #
        # Asking the control itself is the only check that can't be stale.
        # Skipping the repaint here is safe: content assigned before the
        # mount still paints once ``did_mount``'s own ``page.update()``
        # runs.
        if self._panel_frame.page is not None:
            self._panel_frame.update()

    def _pick(self, key: str) -> None:
        entity_ids = self._active_ids
        self.close()
        if entity_ids:
            self._on_pick(entity_ids, key)

    def _create(self, text: str) -> None:
        entity_ids = self._active_ids
        self.close()
        if entity_ids and self._on_create is not None:
            self._on_create(entity_ids, text)


class CategoryPickerButton(SearchPickerButton):
    """Pick an existing category. No create affordance: the taxonomy is
    seeded and managed on its own tab, and inventing categories inline is
    how a category list turns into 400 near-duplicates."""

    def __init__(
        self,
        *,
        categories: list[tuple[str, str]],
        on_pick: Callable[[list[int], str], None],
    ) -> None:
        super().__init__(
            options=categories, on_pick=on_pick, hint="Search categories"
        )

    def update_categories(self, categories: list[tuple[str, str]]) -> None:
        self.update_options(categories)


class MerchantPickerButton(SearchPickerButton):
    """Pick (or name) the payee behind a raw bank descriptor. Creating
    inline is the point here, unlike categories: you discover you need
    "Google" precisely when looking at a row that says
    "YOUTUBEPREMI G.CO/HELPPAY# CA XXXX3007"."""

    def __init__(
        self,
        *,
        merchants: list[tuple[str, str]],
        on_pick: Callable[[list[int], str], None],
        on_create: Callable[[list[int], str], None],
    ) -> None:
        super().__init__(
            options=merchants,
            on_pick=on_pick,
            on_create=on_create,
            hint="Search or name a payee",
        )

    def update_merchants(self, merchants: list[tuple[str, str]]) -> None:
        self.update_options(merchants)


def picker_trigger_cell(
    content: ft.Control,
    width: int | None,
    *,
    on_tap: Callable[[ft.ControlEvent], None],
    tooltip: str | None = None,
) -> ft.Control:
    """The clickable shell a table cell opens a picker through - shared so
    two easy-to-miss fixes don't get re-derived (or drift) per call site:

    - An EXPLICIT ``width``, not ``expand=True``. There's no Row/Column
      ancestor in a plain DataTable cell for ``expand`` to mean anything
      against, and the outer cell Container's own ``alignment=`` (see
      ``build_cell``, controls/data_table.py) makes Flet shrink-wrap the
      child then position it, rather than stretch it - without an
      explicit width matching the column, the actual clickable area is
      just the content's own snug size, not the full column (confirmed
      live: reported as hard to hit).
    - A real ``on_click`` no-op alongside ``on_tap_down``. Only
      ``on_tap_down`` carries the tap coordinates ``open_for`` needs to
      position the popup (Dropdown._toggle's contract), but
      ``on_tap_down`` alone doesn't stop the tap from bubbling to the
      row's own ``on_click`` (DataTable's inline-expand toggle) the way a
      real ``on_click`` does - without this, tapping the cell ALSO
      opened/closed the row underneath the popup.

    ``width=None`` is for a WIDTH-LESS (flex) column, where there's no
    fixed number to claim: the trigger is wrapped in a Row so ``expand``
    finally has a flex parent to mean something against, which is the
    same recipe ``_pending_cell`` (finance_modal.py) already uses to keep
    its text from pushing its buttons off the column edge.
    """
    trigger = ft.Container(
        content=content,
        width=width,
        expand=width is None,
        ink=True,
        border_radius=Theme.Components.BUTTON_RADIUS,
        padding=ft.padding.symmetric(horizontal=8, vertical=4),
        on_tap_down=on_tap,
        on_click=lambda _e: None,
        tooltip=tooltip,
    )
    if width is not None:
        return trigger
    return ft.Row([trigger], spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER)


class BulkActionTrigger(ft.Container):
    """"<Label> (N)" chip: hidden while nothing's selected, opens the
    caller's shared picker for the CURRENT selection on tap. One class for
    every table that supports select-many-then-act (categorize on
    Uncategorized and the register, assign-payee on the register), so the
    styling and the on_tap_down/on_click-noop mechanics (see
    ``picker_trigger_cell``'s own docstring - the same reasoning applies
    here) exist in exactly one place rather than being hand-built per
    panel.
    """

    # This chip sits in the same header row as Add / Connect / Import, so it
    # has to read as one of them - but it can't BE a PulseButton: only
    # ``on_tap_down`` carries the tap coordinates ``open_for`` needs, and
    # ElevatedButton doesn't expose it. So it's a Container wearing the
    # button's look, taken FROM the button's own style rather than re-picked
    # by eye - including the hover states, which a Container has to drive
    # itself since it has no ControlState machinery.
    _STYLE = styles.PULSE_BUTTON_TEAL_STYLE

    @classmethod
    def _state(cls, prop: str, state: ft.ControlState) -> Any:
        """One entry of the shared button style (its per-state props are
        ``{ControlState: value}`` maps; a few are plain values)."""
        value = getattr(cls._STYLE, prop)
        return value[state] if isinstance(value, dict) else value

    def __init__(
        self,
        on_tap: Callable[[ft.ControlEvent], None],
        *,
        label: str = "Categorize",
        tooltip: str = "Set the category for every checked row at once",
    ) -> None:
        self._text = label
        self._idle_bg = self._state("bgcolor", ft.ControlState.DEFAULT)
        self._hover_bg = self._state("bgcolor", ft.ControlState.HOVERED)
        self._idle_fg = self._state("color", ft.ControlState.DEFAULT)
        self._hover_fg = self._state("color", ft.ControlState.HOVERED)
        side = self._state("side", ft.ControlState.DEFAULT)
        self._label = ft.Text(
            label,
            size=styles.PulseButtonTextStyle.size,
            weight=styles.PulseButtonTextStyle.weight,
            font_family=styles.PulseButtonTextStyle.font_family,
            color=self._idle_fg,
        )
        super().__init__(
            content=self._label,
            height=PULSE_BUTTON_COMPACT_HEIGHT,
            alignment=ft.alignment.center,
            border=ft.border.all(side.width, side.color),
            bgcolor=self._idle_bg,
            border_radius=PULSE_BUTTON_COMPACT_RADIUS,
            padding=PULSE_BUTTON_COMPACT_PADDING,
            ink=True,
            visible=False,
            on_tap_down=on_tap,
            on_click=lambda _e: None,
            on_hover=self._on_hover,
            tooltip=tooltip,
        )

    def _on_hover(self, e: ft.ControlEvent) -> None:
        hovering = e.data == "true"
        self.bgcolor = self._hover_bg if hovering else self._idle_bg
        self._label.color = self._hover_fg if hovering else self._idle_fg
        if self.page:
            self.update()

    def set_count(self, count: int) -> None:
        self._label.value = f"{self._text} ({count})" if count else self._text
        self.visible = bool(count)
        if self.page:
            self.update()
