"""
Reusable history-table primitives.

``HoverRevealFilter`` is a pill filter that stays collapsed to an icon and
reveals its options on hover. ``PaginatedHistorySection`` is an API-backed,
filterable, paginated table; subclasses supply columns, a row builder, and
an async ``fetch``. Shared by the worker (task history) and scheduler
(execution history) modals so the filter / pagination / load machinery
lives in exactly one place.
"""

from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import threading
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTableColumn,
    ExpandableDataTable,
    ExpandableRow,
    SecondaryText,
    status_dot,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.log import logger

# (label, api_value, color)
FilterOption = tuple[str, str, str]


def build_status_dot_cell(color: str) -> ft.Container:
    """Centered status dot for the icon column of a history table row."""
    return ft.Container(content=status_dot(color), alignment=ft.alignment.center)


def build_error_detail_block(message: str) -> ft.Container:
    """Styled monospace error box shown in expanded row content."""
    return ft.Container(
        content=ft.Text(message, size=12, color=ft.Colors.ON_SURFACE, selectable=True),
        bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
        border_radius=6,
        padding=ft.padding.all(10),
        border=ft.border.all(1, ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE)),
    )


_PILL_WIDTH = 80
_PILL_HEIGHT = 28
_PILL_SELECTED_OPACITY = 0.15


@dataclass
class FilterSpec:
    """Declarative config for one ``HoverRevealFilter``."""

    icon: str
    options: list[FilterOption]
    dot_color: str


class HoverRevealFilter(ft.Container):
    """An icon that expands to a row of selectable pills on hover.

    ``on_change(value)`` fires when the selection changes. The currently
    selected value is exposed via ``value``.
    """

    def __init__(
        self,
        *,
        icon: str,
        options: list[FilterOption],
        on_change: Callable[[str], None],
        dot_color: str,
        default: str = "all",
    ) -> None:
        super().__init__()
        self._options = options
        self._on_change = on_change
        self._current = default
        self._collapse_timer: threading.Timer | None = None
        anim = ft.Animation(200, ft.AnimationCurve.EASE_OUT)

        self._pills = [
            self._build_pill(label, value, color) for label, value, color in options
        ]
        self._wrapper = ft.Container(
            content=ft.Row(self._pills, spacing=Theme.Spacing.XS),
            width=0,
            opacity=0,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            animate=anim,
            animate_opacity=anim,
        )
        self._dot = ft.Container(
            width=6,
            height=6,
            border_radius=3,
            bgcolor=dot_color,
            opacity=0,
            animate_opacity=anim,
        )
        self.content = ft.Row(
            [
                self._wrapper,
                self._dot,
                ft.Icon(icon, size=16, color=Theme.Colors.TEXT_SECONDARY),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.on_hover = self._handle_hover

    @property
    def value(self) -> str:
        return self._current

    def _build_pill(self, label: str, value: str, color: str) -> ft.Container:
        is_selected = value == self._current
        return ft.Container(
            content=ft.Text(
                label,
                size=Theme.Typography.BODY_SMALL,
                weight=Theme.Typography.WEIGHT_SEMIBOLD,
                color=color if is_selected else Theme.Colors.TEXT_SECONDARY,
                text_align=ft.TextAlign.CENTER,
            ),
            width=_PILL_WIDTH,
            height=_PILL_HEIGHT,
            alignment=ft.alignment.center,
            border_radius=Theme.Components.BADGE_RADIUS,
            bgcolor=(
                ft.Colors.with_opacity(_PILL_SELECTED_OPACITY, color)
                if is_selected
                else ft.Colors.TRANSPARENT
            ),
            on_click=lambda e, v=value: self.select(v),
            ink=True,
        )

    def select(self, value: str) -> None:
        """Select a value, repaint pills, and fire ``on_change`` if changed."""
        if value == self._current:
            return
        self._current = value
        for pill, (_, option_value, color) in zip(
            self._pills, self._options, strict=False
        ):
            is_selected = option_value == value
            pill.bgcolor = (
                ft.Colors.with_opacity(_PILL_SELECTED_OPACITY, color)
                if is_selected
                else ft.Colors.TRANSPARENT
            )
            pill.content.color = color if is_selected else Theme.Colors.TEXT_SECONDARY
        if self.page:
            with contextlib.suppress(Exception):
                self.update()
        self._on_change(value)

    def _handle_hover(self, e: ft.HoverEvent) -> None:
        if e.data == "true":
            if self._collapse_timer:
                self._collapse_timer.cancel()
                self._collapse_timer = None
            self._wrapper.width = len(self._options) * (_PILL_WIDTH + 4)
            self._wrapper.opacity = 1
            self._dot.opacity = 0
            self._safe_update()
        else:
            self._collapse_timer = threading.Timer(0.4, self._delayed_collapse)
            self._collapse_timer.start()

    def _delayed_collapse(self) -> None:
        self._collapse_timer = None
        self._wrapper.width = 0
        self._wrapper.opacity = 0
        self._update_dot()
        self._safe_update()

    def _update_dot(self) -> None:
        if self._current != "all":
            for _, value, color in self._options:
                if value == self._current:
                    self._dot.bgcolor = color
                    break
            self._dot.opacity = 1
        else:
            self._dot.opacity = 0

    def _safe_update(self) -> None:
        if self.page:
            with contextlib.suppress(Exception):
                self.update()


class PaginatedHistorySection(ft.Container):
    """API-backed, filterable, paginated history table.

    Subclasses implement ``fetch`` (returns ``(records, total)``) and
    ``build_row``; the base owns the filters, refresh, loading indicator,
    pagination, and the load orchestration. Filter values are read via
    ``self.filters["<name>"].value`` inside ``fetch``.
    """

    PAGE_SIZE = 25

    def __init__(
        self,
        page: ft.Page,
        *,
        columns: list[DataTableColumn],
        empty_message: str,
        filter_specs: dict[str, FilterSpec],
    ) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD
        self._page = page
        self._offset = 0
        self._total = 0
        self._loading = False

        self.filters: dict[str, HoverRevealFilter] = {}
        filter_controls: list[ft.Control] = []
        for name, spec in filter_specs.items():
            control = HoverRevealFilter(
                icon=spec.icon,
                options=spec.options,
                on_change=self.reload,
                dot_color=spec.dot_color,
            )
            self.filters[name] = control
            filter_controls.append(control)

        self._refresh_btn = ft.IconButton(
            icon=ft.Icons.REFRESH,
            icon_color=ft.Colors.ON_SURFACE_VARIANT,
            icon_size=16,
            tooltip="Refresh",
            on_click=self._on_refresh,
        )
        self._loading_indicator = ft.ProgressRing(
            width=16, height=16, stroke_width=2, visible=False
        )
        self._page_info = SecondaryText("", size=12)
        self._prev_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            icon_color=ft.Colors.ON_SURFACE_VARIANT,
            icon_size=16,
            tooltip="Previous",
            on_click=self._on_prev,
            disabled=True,
        )
        self._next_btn = ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT,
            icon_color=ft.Colors.ON_SURFACE_VARIANT,
            icon_size=16,
            tooltip="Next",
            on_click=self._on_next,
            disabled=True,
        )

        toolbar = ft.Row(
            [
                *filter_controls,
                self._refresh_btn,
                self._loading_indicator,
                ft.Container(expand=True),
                self._prev_btn,
                self._page_info,
                self._next_btn,
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._table = ExpandableDataTable(
            columns=columns,
            rows=[],
            row_padding=6,
            empty_message=empty_message,
        )
        self.content = ft.Column([toolbar, self._table], spacing=Theme.Spacing.SM)

    # ── subclass hooks ───────────────────────────────────────────────────

    async def fetch(self, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Return ``(records, total)`` for the given page."""
        raise NotImplementedError

    def build_row(self, record: dict[str, Any]) -> ExpandableRow:
        """Build a table row from a record."""
        raise NotImplementedError

    def api_client(self) -> Any:
        """The session's API client (call from ``fetch``)."""
        from app.components.frontend.state.session_state import get_session_state

        return get_session_state(self.page).api_client

    # ── load orchestration ───────────────────────────────────────────────

    def reload(self, _value: str | None = None) -> None:
        """Reset to the first page and reload (filter ``on_change`` target)."""
        self._offset = 0
        self._schedule_load()

    def did_mount(self) -> None:
        self._schedule_load()

    def _schedule_load(self) -> None:
        if self._page and hasattr(self._page, "run_task"):
            self._page.run_task(self._load_data)

    async def _load_data(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._loading_indicator.visible = True
        with contextlib.suppress(Exception):
            self._loading_indicator.update()

        try:
            records, total = await self.fetch(self._offset, self.PAGE_SIZE)
            self._total = total
            rows = [self.build_row(record) for record in records]
            self._table._rows = rows
            self._table._expanded = [False] * len(rows)
            self._table._build()
            self._update_pagination()
            self._table.update()
        except Exception as e:
            logger.debug(f"Failed to load history: {e}")
        finally:
            self._loading = False
            self._loading_indicator.visible = False
            with contextlib.suppress(Exception):
                self._loading_indicator.update()

    def _update_pagination(self) -> None:
        end = min(self._offset + self.PAGE_SIZE, self._total)
        self._page_info.value = (
            f"{self._offset + 1}-{end} of {self._total}"
            if self._total > 0
            else "No records"
        )
        self._prev_btn.disabled = self._offset <= 0
        self._next_btn.disabled = (self._offset + self.PAGE_SIZE) >= self._total
        with contextlib.suppress(Exception):
            self._page_info.update()
            self._prev_btn.update()
            self._next_btn.update()

    def _on_refresh(self, e: ft.ControlEvent) -> None:
        self._schedule_load()

    def _on_prev(self, e: ft.ControlEvent) -> None:
        self._offset = max(0, self._offset - self.PAGE_SIZE)
        self._schedule_load()

    def _on_next(self, e: ft.ControlEvent) -> None:
        if self._offset + self.PAGE_SIZE < self._total:
            self._offset += self.PAGE_SIZE
            self._schedule_load()
