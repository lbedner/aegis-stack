"""The search-and-pick popup, and the three things it picks.

Category, merchant and tag differ in what they load and what they
call on confirm, which is why they are subclasses rather than a
flag - the base owns the filtering and the row rendering.
"""

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls.dropdown import Dropdown
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

_PANEL_MAX_HEIGHT = 560
_PANEL_WIDTH = 320
_COUNT_LABEL_HEIGHT = 20
_ROWS_HEIGHT = _PANEL_MAX_HEIGHT - (2 * 8 + _COUNT_LABEL_HEIGHT + 36 + 1 + 3 * 8)


def _filter_options(
    options: list[tuple[str, str]], query: str
) -> list[tuple[str, str]]:
    """Case-insensitive substring filter over (key, label) options."""
    q = query.strip().casefold()
    return [(k, t) for k, t in options if q in t.casefold()] if q else options


def _option_row(
    label: str, on_click: Callable[[ft.ControlEvent], None], color: str
) -> ft.Container:
    """One pickable row. XS padding, not SM: these lists can run to
    hundreds of entries (267 categories in testing) and search only
    narrows so far before the first character is typed - a denser row
    shows more per screenful without scrolling."""
    return ft.Container(
        content=ft.Text(label, size=13, color=color),
        on_click=on_click,
        ink=True,
        border_radius=Theme.Components.BUTTON_RADIUS,
        padding=ft.padding.symmetric(
            vertical=Theme.Spacing.XS, horizontal=Theme.Spacing.MD
        ),
    )


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
        return _option_row(label, on_click, color)

    def _render_rows(self, query: str) -> None:
        typed = query.strip()
        q = typed.casefold()
        matches = _filter_options(self._options, query)
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
    """Pick a category, and optionally name one that does not exist yet.

    Creating inline was withheld for a long time on the grounds that
    "inventing categories inline is how a category list turns into 400
    near-duplicates". That risk is real, but it is answered where it
    belongs: the resolver behind ``on_create`` is get-or-CREATE keyed on
    a normalized slug, so "kids: activities" lands ON "Kids:Activities"
    rather than beside it, and a third path segment folds back to two.
    The picker also hides the create row entirely once the typed text
    matches something, so the common near-miss never gets offered.

    ``on_create`` is OPT-IN: a caller with nowhere to save a new category
    passes nothing and the affordance does not appear.
    """

    def __init__(
        self,
        *,
        categories: list[tuple[str, str]],
        on_pick: Callable[[list[int], str], None],
        on_create: Callable[[list[int], str], None] | None = None,
    ) -> None:
        super().__init__(
            options=categories,
            on_pick=on_pick,
            on_create=on_create,
            hint="Search categories",
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


class TagPickerButton(SearchPickerButton):
    """Pick (or invent) the tag to put on the selected transactions.

    Creating inline is the whole feature: a "flag" is not a built-in bit
    but whatever tag the user names in the moment ("Flagged", "Check with
    Sarah", "Tax 2026"), and the resolver behind both pick and create is
    the same get-or-create keyed on a normalized name - so picking an
    existing tag and typing its near-miss land on the same row."""

    def __init__(
        self,
        *,
        tags: list[tuple[str, str]],
        on_pick: Callable[[list[int], str], None],
        on_create: Callable[[list[int], str], None],
    ) -> None:
        super().__init__(
            options=tags,
            on_pick=on_pick,
            on_create=on_create,
            hint="Search or name a tag",
        )

    def update_tags(self, tags: list[tuple[str, str]]) -> None:
        self.update_options(tags)
