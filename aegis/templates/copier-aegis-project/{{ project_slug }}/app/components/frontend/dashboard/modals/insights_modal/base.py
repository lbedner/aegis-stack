"""The shared tab base: data loading, range selection, empty states."""

from __future__ import annotations  # noqa: I001

from typing import Any

import flet as ft

from app.components.frontend.dashboard.modals.insights_modal.constants import (
    RANGE_OPTIONS,
)

from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.insights.models import EVENT_TYPE_LABELS
from app.services.insights.schemas import BulkInsightsResponse
from app.services.insights.views.events import (
    group_events,
)

from ..modal_sections import (
    ChartColors,
    DateRangeChips,
)


# Event type → chip border/highlight color

# Shared date range options for all tabs

# Milestone category config (for Overview trophy cards)

# Event type to status mapping (for activity feed dot colors)


class InsightsTab(ft.Container):
    """Base class for insight tabs with date range chips, events toggle, and rebuild pattern."""  # noqa: E501

    _default_days: int = 7  # Override in subclass

    def __init__(self, bulk: BulkInsightsResponse | None = None) -> None:
        super().__init__()

        self._bulk = bulk
        self._days = self._default_days
        self._data = self._load_data(self._days)
        self._highlighted_dates: set[str] = set()
        # Selection / filter state mirroring the aegis-pulse event-chip
        # macro. `_selected_event_id` is None when no chip is selected.
        # `_selected_event_types` is the explicit set of event types
        # shown in the chip strip and as chart annotations - empty
        # means "no events selected", so chips are hidden and the
        # chart shows no event markers. The "All" toggle row in the
        # filter dropdown selects every type present in the data.
        self._selected_event_id: str | None = None
        self._selected_event_types: set[str] = set()
        self._content_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

        # Date-range pills — owned by `DateRangeChips`, which keeps its
        # own selection state and styling so this base class only has to
        # react to the change.
        self._range_chips = DateRangeChips(
            options=RANGE_OPTIONS,
            selected_days=self._days,
            on_change=self._on_range_change,
        )

        self._build_content()

        self.content = self._content_column
        self.padding = ft.padding.only(
            left=Theme.Spacing.MD,
            top=Theme.Spacing.MD,
            bottom=Theme.Spacing.MD,
            right=Theme.Spacing.LG + 8,
        )
        self.expand = True

    def _on_event_click(self, dates: set[str]) -> None:
        if self._highlighted_dates == dates:
            self._highlighted_dates = set()
        else:
            self._highlighted_dates = dates
        self._build_content()
        self._content_column.update()

    def _on_range_change(self, days: int) -> None:
        self._days = days
        self._data = self._load_data(days)
        # `DateRangeChips` already updated its own active pill before
        # invoking this callback, so we only have to react: reload data
        # and rebuild the tab content for the new window.
        self._build_content()
        self._content_column.update()

    def _build_content(self) -> None:
        """Override in subclass to build tab-specific content."""
        raise NotImplementedError

    def _load_data(self, days: int = 14) -> dict[str, Any]:
        """Override in subclass to load tab-specific data."""
        raise NotImplementedError

    def _make_filter_bar(
        self, last_updated: str = "", extra_controls: list[ft.Control] | None = None
    ) -> ft.Row:
        """Build the standard filter bar with range chips and last-updated.

        The Events filter dropdown lives on the chip strip itself
        (see `_render_event_chips`), so it isn't included here.
        """
        right_items: list[ft.Control] = []
        if last_updated:
            right_items.append(
                SecondaryText(
                    f"Last updated: {last_updated}", size=Theme.Typography.BODY_SMALL
                )
            )
        if extra_controls:
            right_items.extend(extra_controls)
        return ft.Row(
            [self._range_chips, ft.Row(right_items, spacing=Theme.Spacing.MD)],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

    def _render_event_chips(
        self,
        all_events: list[tuple[str, str, str]],
        valid_dates: set[str] | None = None,
        exclude_types: set[str] | None = None,
    ) -> ft.Control | None:
        """Render the event chip strip + filter dropdown.

        Mirrors the aegis-pulse `alpine_event_chips` macro — uniform
        muted-card chip styling, teal accent for the selected chip,
        amber for chips on the same date as the selection, and a
        right-aligned "Events (N)" dropdown that filters the strip by
        event type. Returns a Column with the filter row above the chip
        row. The filter trigger is always shown; the chip row only
        renders when there are events to display under the current
        filter.
        """
        if exclude_types:
            all_events = [
                (d, lbl, t) for d, lbl, t in all_events if t not in exclude_types
            ]
        if valid_dates is not None:
            all_events = [(d, lbl, t) for d, lbl, t in all_events if d in valid_dates]

        # Apply the dropdown's type filter. Empty set means "no events
        # selected" — chip strip stays empty, button reads neutral.
        # Non-empty restricts to the selected types.
        visible_events = [
            (d, lbl, t) for d, lbl, t in all_events if t in self._selected_event_types
        ]

        # The service groups newest-first for the timeline; the chip strip
        # reads left to right, oldest first.
        grouped = list(reversed(group_events(visible_events, self._days)))
        if not all_events:
            # Nothing to filter and nothing to show — hide the toolbar
            # entirely so empty tabs don't get a stray "Events" button.
            return None

        # Build the filter dropdown. Lists every event type present in
        # the un-filtered set, plus an "All" toggle-all row at the top.
        present_types = sorted({t for _d, _lbl, t in all_events})
        all_selected = bool(present_types) and set(present_types).issubset(
            self._selected_event_types
        )
        active_filter = bool(self._selected_event_types)
        filter_label = f"Events ({len(grouped)})" if active_filter else "Events"
        filter_button = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Text(
                    filter_label,
                    size=Theme.Typography.BODY_SMALL,
                    weight=ft.FontWeight.W_500,
                    color=ft.Colors.ON_SURFACE
                    if active_filter
                    else ft.Colors.ON_SURFACE_VARIANT,
                ),
                bgcolor=ft.Colors.with_opacity(0.10, ChartColors.TEAL)
                if active_filter
                else ft.Colors.SURFACE_CONTAINER_HIGHEST,
                border=ft.border.all(
                    0.5,
                    ChartColors.TEAL if active_filter else ft.Colors.OUTLINE,
                ),
                border_radius=10,
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
            ),
            items=[
                ft.PopupMenuItem(
                    text=("✓ All" if all_selected else "All"),
                    on_click=lambda _e, types=present_types: (
                        self._on_event_types_toggle_all(types)
                    ),
                ),
                *[
                    ft.PopupMenuItem(
                        text=(
                            f"✓ {EVENT_TYPE_LABELS.get(t, t)}"
                            if t in self._selected_event_types
                            else EVENT_TYPE_LABELS.get(t, t)
                        ),
                        on_click=lambda _e, et=t: self._on_event_type_toggle(et),
                    )
                    for t in present_types
                ],
            ],
        )

        highlighted = self._highlighted_dates

        chip_controls: list[ft.Control] = []
        for date, label, etype, dates_set in grouped:
            chip_id = f"{date}::{label}::{etype}"
            is_selected = chip_id == self._selected_event_id
            is_related = not is_selected and bool(dates_set & highlighted)
            if is_selected:
                chip_bg = ft.Colors.with_opacity(0.10, ChartColors.TEAL)
                chip_border_color = ChartColors.TEAL
                chip_text_color = ft.Colors.ON_SURFACE
            elif is_related:
                chip_bg = ft.Colors.with_opacity(0.10, ChartColors.AMBER)
                chip_border_color = ChartColors.AMBER
                chip_text_color = ft.Colors.ON_SURFACE
            else:
                chip_bg = ft.Colors.SURFACE_CONTAINER_HIGHEST
                chip_border_color = ft.Colors.OUTLINE
                chip_text_color = ft.Colors.ON_SURFACE_VARIANT
            chip_controls.append(
                ft.Container(
                    content=ft.Text(
                        f"{label}  {date[-5:]}",
                        size=Theme.Typography.BODY_SMALL,
                        weight=ft.FontWeight.W_500,
                        color=chip_text_color,
                        selectable=False,
                    ),
                    bgcolor=chip_bg,
                    border=ft.border.all(0.5, chip_border_color),
                    border_radius=10,
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                    on_click=lambda _e, cid=chip_id, ds=dates_set: (
                        self._on_event_chip_click(cid, ds)
                    ),
                    ink=True,
                )
            )

        return ft.Column(
            [
                ft.Row(
                    [filter_button],
                    alignment=ft.MainAxisAlignment.END,
                ),
                ft.Row(chip_controls, spacing=6, wrap=True),
            ],
            spacing=6,
        )

    def _on_event_chip_click(self, chip_id: str, dates_set: set[str]) -> None:
        """Toggle chip selection. Clicking the same chip again clears
        the highlight; clicking a different chip moves the highlight to
        its date(s)."""
        if self._selected_event_id == chip_id:
            self._selected_event_id = None
            self._highlighted_dates = set()
        else:
            self._selected_event_id = chip_id
            self._highlighted_dates = set(dates_set)
        self._build_content()
        self._content_column.update()

    def _on_event_type_toggle(self, event_type: str) -> None:
        """Toggle membership of an event type in the filter dropdown."""
        if event_type in self._selected_event_types:
            self._selected_event_types.discard(event_type)
        else:
            self._selected_event_types.add(event_type)
        self._build_content()
        self._content_column.update()

    def _on_event_types_toggle_all(self, types: list[str]) -> None:
        """Dropdown's "All" row — toggle all event types on or off.

        If every type is already selected, clear the set (hides the
        chip strip and turns the button neutral). Otherwise select
        every available type, showing the full chip strip with the
        button in its teal/active state.
        """
        type_set = set(types)
        if type_set.issubset(self._selected_event_types) and self._selected_event_types:
            self._selected_event_types = set()
        else:
            self._selected_event_types = type_set
        self._build_content()
        self._content_column.update()
