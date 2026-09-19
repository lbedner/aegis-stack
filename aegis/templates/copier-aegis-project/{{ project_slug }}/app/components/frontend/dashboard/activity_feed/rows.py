"""One event, or one group of them, as a row you can expand."""

from datetime import datetime

import flet as ft

from app.components.frontend.controls import (
    DataTableColumn,
    PrimaryText,
    SecondaryText,
    Tag,
)
from app.components.frontend.dashboard.activity_feed.grouping import (
    EventGroup,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.activity import ActivityEvent

from ..cards.card_utils import get_status_color

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
