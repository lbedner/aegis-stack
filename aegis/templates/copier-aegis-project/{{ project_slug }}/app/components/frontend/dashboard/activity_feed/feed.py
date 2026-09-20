"""The feed itself: what it holds, and how it repaints."""

import threading

import flet as ft

from app.components.frontend.controls import (
    SecondaryText,
    SeverityFilter,
)
from app.components.frontend.controls.data_table import DataTableRow
from app.components.frontend.dashboard.activity_feed.grouping import (
    _STATUS_SEVERITY,
    EventGroup,
    _item_key,
    group_consecutive_events,
)
from app.components.frontend.dashboard.activity_feed.rows import (
    _ROW_COLUMN,
    ExpandableActivityRow,
    GroupedActivityRow,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import activity
from app.services.system.activity import ActivityEvent


class ActivityFeed(ft.Container):
    """
    Activity feed panel showing recent system events.

    Composes a custom header (with inline severity filter) and a scrollable
    ListView of DataTableRow-wrapped activity rows. This replaces the previous
    DataTable approach to embed the filter inside the header row.
    """

    def __init__(self, max_events: int = 40) -> None:
        super().__init__()
        self._max_events = max_events
        self._rows_by_key: dict[str, ExpandableActivityRow | GroupedActivityRow] = {}
        self._current_events: list[ActivityEvent] = []
        self._min_severity = 0
        self._row_padding = 10

        # Severity filter (inline in header, hidden until hover)
        self._severity_filter = SeverityFilter(on_change=self._on_severity_change)
        self._collapse_timer: threading.Timer | None = None
        self._pills_expanded = False

        # Animated wrapper around filter pills — starts collapsed
        _anim = ft.Animation(200, ft.AnimationCurve.EASE_OUT)
        self._filter_wrapper = ft.Container(
            content=self._severity_filter,
            width=0,
            opacity=0,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            animate=_anim,
            animate_opacity=_anim,
        )

        # Colored indicator dot
        # (visible when a non-"All" filter is active and pills collapsed)
        self._filter_dot = ft.Container(
            width=6,
            height=6,
            border_radius=3,
            bgcolor=Theme.Colors.ACCENT,
            opacity=0,
            animate_opacity=_anim,
        )

        # Filter icon (always visible)
        self._filter_icon = ft.Icon(
            ft.Icons.FILTER_LIST,
            size=16,
            color=Theme.Colors.TEXT_SECONDARY,
        )

        # Filter zone: hover here to expand pills (icon + dot + wrapper)
        self._filter_zone = ft.Container(
            content=ft.Row(
                [self._filter_wrapper, self._filter_dot, self._filter_icon],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_hover=self._handle_header_hover,
        )

        # Header: "Activity" label + filter zone
        self._header = ft.Container(
            content=ft.Row(
                [
                    SecondaryText("Activity", size=Theme.Typography.BODY_SMALL),
                    self._filter_zone,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.MD, vertical=self._row_padding + 2
            ),
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE)),
        )

        # Scrollable row list
        self._list_view = ft.ListView(controls=[], spacing=0, expand=True)

        # Build initial rows
        self._build_rows()

        # Outer container: card styling matching DataTable
        self.content = ft.Column(
            [self._header, self._list_view], spacing=0, expand=True
        )
        self.bgcolor = ft.Colors.SURFACE
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(1, ft.Colors.OUTLINE)
        self.expand = True

    # -- Hover-expand filter methods ------------------------------------------

    def _handle_header_hover(self, e: ft.HoverEvent) -> None:
        """Expand filter pills on hover enter, schedule collapse on leave."""
        if e.data == "true":
            if self._collapse_timer:
                self._collapse_timer.cancel()
                self._collapse_timer = None
            self._expand_filter()
        else:
            self._collapse_timer = threading.Timer(0.3, self._delayed_collapse)
            self._collapse_timer.start()

    def _expand_filter(self) -> None:
        """Reveal the severity pills."""
        self._pills_expanded = True
        self._filter_wrapper.width = 268
        self._filter_wrapper.opacity = 1
        self._filter_dot.opacity = 0
        if self.page:
            self.page.update(self._header)

    def _collapse_filter(self) -> None:
        """Hide the severity pills and show dot if filtered."""
        self._pills_expanded = False
        self._filter_wrapper.width = 0
        self._filter_wrapper.opacity = 0
        self._update_filter_dot()

    def _delayed_collapse(self) -> None:
        """Timer callback — collapse pills and push update."""
        self._collapse_timer = None
        self._collapse_filter()
        if self.page:
            self.page.update(self._header)

    def _update_filter_dot(self) -> None:
        """Show/hide the indicator dot based on active filter."""
        if self._min_severity > 0:
            self._filter_dot.bgcolor = self._severity_filter.selected_color
            self._filter_dot.opacity = 1
        else:
            self._filter_dot.opacity = 0

    # -- Severity change handler -----------------------------------------------

    def _on_severity_change(self, min_severity: int) -> None:
        """Handle severity filter change."""
        self._min_severity = min_severity
        # Pre-set dot color so it's ready when pills collapse
        self._filter_dot.bgcolor = self._severity_filter.selected_color
        self.refresh()
        self.update()

    def _filter_events(self, events: list[ActivityEvent]) -> list[ActivityEvent]:
        """Filter events by the current minimum severity."""
        if self._min_severity == 0:
            return events
        return [
            e
            for e in events
            if _STATUS_SEVERITY.get(e.status.lower(), 0) >= self._min_severity
        ]

    def _wrap_in_row(
        self, content: ExpandableActivityRow | GroupedActivityRow
    ) -> DataTableRow:
        """Wrap an activity row inside a DataTableRow for hover/border styling."""
        return DataTableRow(
            columns=_ROW_COLUMN,
            row_data=[content],
            padding=self._row_padding,
        )

    def _build_rows(self) -> None:
        """Build the row list with current events, grouping consecutive alerts."""
        events = activity.get_recent(limit=self._max_events)
        self._current_events = events
        filtered = self._filter_events(events)

        if filtered:
            grouped = group_consecutive_events(filtered)
            rows: list[ft.Control] = []
            for item in grouped:
                row = self._create_row(item)
                key = _item_key(item)
                self._rows_by_key[key] = row
                rows.append(self._wrap_in_row(row))
        else:
            placeholder_event = ActivityEvent(
                component="system",
                event_type="info",
                message="Waiting for events...",
                status="success",
            )
            rows = [self._wrap_in_row(ExpandableActivityRow(placeholder_event))]

        self._list_view.controls = rows

    def refresh(self) -> None:
        """Refresh with in-place updates to preserve expanded state."""
        new_events = activity.get_recent(limit=self._max_events)

        if not new_events:
            return

        filtered = self._filter_events(new_events)
        new_grouped = group_consecutive_events(filtered)
        new_keys = {_item_key(item) for item in new_grouped}
        old_keys = set(self._rows_by_key.keys())

        added_keys = new_keys - old_keys
        removed_keys = old_keys - new_keys
        kept_keys = new_keys & old_keys

        # Update time display on existing rows
        for key in kept_keys:
            row = self._rows_by_key.get(key)
            if row:
                row.update_time()

        # Remove stale rows from tracking
        for key in removed_keys:
            self._rows_by_key.pop(key, None)

        # Create new rows for added items
        for item in new_grouped:
            key = _item_key(item)
            if key in added_keys:
                self._rows_by_key[key] = self._create_row(item)

        # Rebuild list view rows in correct order (reusing existing row objects)
        rows: list[ft.Control] = []
        for item in new_grouped:
            key = _item_key(item)
            row = self._rows_by_key.get(key)
            if row:
                rows.append(self._wrap_in_row(row))

        self._current_events = new_events
        self._list_view.controls = rows

    def _create_row(
        self, item: ActivityEvent | EventGroup
    ) -> ExpandableActivityRow | GroupedActivityRow:
        """Create the appropriate row type for an item."""
        if isinstance(item, EventGroup):
            return GroupedActivityRow(item)
        return ExpandableActivityRow(item)
