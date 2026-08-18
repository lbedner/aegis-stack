"""
Activity Feed Panel

Shows recent system activity and events with inline severity filtering.
Groups consecutive alerts from the same component to keep the feed scannable.
"""

from dataclasses import dataclass
from datetime import datetime
import threading

import flet as ft

from app.components.frontend.controls import (
    DataTableColumn,
    PrimaryText,
    SecondaryText,
    SeverityFilter,
    Tag,
)
from app.components.frontend.controls.data_table import DataTableRow
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import activity
from app.services.system.activity import ActivityEvent

from .cards.card_utils import get_status_color

# Minimum consecutive same-component alerts before grouping
GROUP_THRESHOLD = 2

# Severity ranking for worst_status calculation (higher = worse)
_STATUS_SEVERITY: dict[str, int] = {
    "success": 0,
    "healthy": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
    "unhealthy": 3,
}

# Single-column definition used only for DataTableRow cell layout
_ROW_COLUMN = [DataTableColumn("Activity")]


def format_relative_time(timestamp: datetime) -> str:
    """Format timestamp as relative time."""
    now = datetime.now()
    diff = now - timestamp

    seconds = diff.total_seconds()
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        if timestamp.hour == 0 and timestamp.minute == 0:
            return timestamp.strftime("%b %d")
        return timestamp.strftime("%b %d %H:%M")


@dataclass
class EventGroup:
    """UI-only grouping of consecutive same-component events."""

    component: str
    events: list[ActivityEvent]  # newest first (matches feed order)

    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def latest_event(self) -> ActivityEvent:
        return self.events[0]

    @property
    def worst_status(self) -> str:
        """Return the most severe status in the group."""
        worst = "success"
        worst_sev = 0
        for event in self.events:
            sev = _STATUS_SEVERITY.get(event.status.lower(), 0)
            if sev > worst_sev:
                worst_sev = sev
                worst = event.status
        return worst

    @property
    def group_key(self) -> str:
        """Key based on component + count + oldest event timestamp.

        Count is included so the key changes when new events join the group,
        forcing refresh to rebuild the row instead of reusing the stale one.
        """
        oldest = self.events[-1]
        return f"{self.component}:{self.count}:{oldest.timestamp.isoformat()}"


def group_consecutive_events(
    events: list[ActivityEvent],
) -> list[ActivityEvent | EventGroup]:
    """Group consecutive same-component events into EventGroups.

    Single O(n) pass. Runs of fewer than GROUP_THRESHOLD are passed through
    as individual events.
    """
    if not events:
        return []

    result: list[ActivityEvent | EventGroup] = []
    run: list[ActivityEvent] = [events[0]]

    for event in events[1:]:
        if event.component == run[0].component:
            run.append(event)
        else:
            _flush_run(run, result)
            run = [event]

    _flush_run(run, result)
    return result


def _flush_run(
    run: list[ActivityEvent],
    result: list[ActivityEvent | EventGroup],
) -> None:
    """Flush accumulated run into result list."""
    if len(run) >= GROUP_THRESHOLD:
        result.append(EventGroup(component=run[0].component, events=run))
    else:
        result.extend(run)


class ExpandableActivityRow(ft.Container):
    """An expandable activity row that shows details when clicked."""

    def __init__(self, event: ActivityEvent) -> None:
        super().__init__()
        self._event = event
        self._expanded = False
        self._expand_icon: ft.Icon | None = None

        # Status dot color (uses utility for consistency across components)
        dot_color = get_status_color(event.status)
        time_ago = format_relative_time(event.timestamp)

        # Store reference to time text for updates
        self._time_text = SecondaryText(time_ago)

        # Build the header row content
        header_content = ft.Row(
            [
                # Status dot
                ft.Container(
                    width=8,
                    height=8,
                    bgcolor=dot_color,
                    border_radius=4,
                    margin=ft.margin.only(right=8),
                ),
                # Stacked title + subtitle (expand to fill)
                ft.Column(
                    [
                        PrimaryText(event.message),
                        self._time_text,  # Use stored reference
                    ],
                    spacing=2,
                    expand=True,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Add expand icon if there are details
        if event.details:
            self._expand_icon = ft.Icon(
                ft.Icons.EXPAND_MORE,
                size=16,
                color=Theme.Colors.TEXT_SECONDARY,
            )
            header_content.controls.append(self._expand_icon)

        # Details section (hidden by default)
        self._details_container = ft.Container(
            content=SecondaryText(event.details or ""),
            padding=ft.padding.only(left=20, top=8, bottom=4),
            visible=False,
        )

        self.content = ft.Column(
            [header_content, self._details_container],
            spacing=0,
        )
        # No hover handler - DataTableRow handles hover effects
        self.on_click = self._toggle_expand if event.details else None

    def _toggle_expand(self, e: ft.ControlEvent) -> None:
        """Toggle the expanded state."""
        self._expanded = not self._expanded
        self._details_container.visible = self._expanded

        # Rotate the expand icon
        if self._expand_icon:
            self._expand_icon.name = (
                ft.Icons.EXPAND_LESS if self._expanded else ft.Icons.EXPAND_MORE
            )

        # Use page from event - control's page reference may be stale after refresh
        if e.page:
            e.page.update(self)

    def update_time(self) -> None:
        """Update the relative time display."""
        if self._time_text:
            self._time_text.value = format_relative_time(self._event.timestamp)


class GroupedActivityRow(ft.Container):
    """A collapsible group of consecutive same-component alerts."""

    def __init__(self, group: EventGroup) -> None:
        super().__init__()
        self._group = group
        self._expanded = False

        # Build child rows (created once, reused across expand/collapse)
        self._child_rows = [ExpandableActivityRow(e) for e in group.events]

        # Dot color reflects latest (most recent) event status
        dot_color = get_status_color(group.latest_event.status)
        time_ago = format_relative_time(group.latest_event.timestamp)

        # Store reference to time text for updates
        self._time_text = SecondaryText(time_ago)

        # Count badge
        self._count_tag = Tag(
            f"{group.count} alerts",
            color=dot_color,
        )

        # Expand/collapse icon
        self._expand_icon = ft.Icon(
            ft.Icons.EXPAND_MORE,
            size=16,
            color=Theme.Colors.TEXT_SECONDARY,
        )

        # Component display name (capitalize first letter)
        display_name = group.component.replace("_", " ").title()

        # Header row: dot + name + count badge + time + expand icon
        self._header = ft.Row(
            [
                # Status dot
                ft.Container(
                    width=8,
                    height=8,
                    bgcolor=dot_color,
                    border_radius=4,
                    margin=ft.margin.only(right=8),
                ),
                # Component name + time (expand to fill)
                ft.Column(
                    [
                        PrimaryText(display_name),
                        self._time_text,
                    ],
                    spacing=2,
                    expand=True,
                ),
                self._count_tag,
                self._expand_icon,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # Child rows container (hidden by default)
        self._children_container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=row,
                        padding=ft.padding.only(left=16),
                    )
                    for row in self._child_rows
                ],
                spacing=0,
            ),
            visible=False,
        )

        self.content = ft.Column(
            [self._header, self._children_container],
            spacing=0,
        )
        self.on_click = self._toggle_expand

    def _toggle_expand(self, e: ft.ControlEvent) -> None:
        """Toggle expanded state showing/hiding individual alerts."""
        self._expanded = not self._expanded
        self._children_container.visible = self._expanded
        self._expand_icon.name = (
            ft.Icons.EXPAND_LESS if self._expanded else ft.Icons.EXPAND_MORE
        )
        if e.page:
            e.page.update(self)

    def update_time(self) -> None:
        """Update time display on summary and all child rows."""
        if self._time_text:
            self._time_text.value = format_relative_time(
                self._group.latest_event.timestamp
            )
        for row in self._child_rows:
            row.update_time()


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


def _item_key(item: ActivityEvent | EventGroup) -> str:
    """Return a stable string key for an event or group."""
    if isinstance(item, EventGroup):
        return item.group_key
    return item.timestamp.isoformat()
