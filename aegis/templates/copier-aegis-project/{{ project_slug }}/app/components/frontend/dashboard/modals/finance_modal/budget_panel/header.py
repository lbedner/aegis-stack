"""What sits above the budget tabs: the stats strip and the pager."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_stats_cells,
    outlook_chip,
    outlook_stats_cells,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.base import (
    BudgetPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.finance_modal.stat_details import (
    _captioned,
    equation_rows,
    stat_window_label,
)
from app.components.frontend.theme import AegisTheme as Theme


class BudgetHeaderMixin(BudgetPanelState):
    """The month you are looking at, and the four numbers for it.

    Each stat opens its own rows; the pager moves the whole panel a
    month at a time without refetching.
    """

    def _stats_strip(self, stats: dict[str, Any]) -> ft.Control:
        # Paged past "this month", the four cells recompute for that
        # future month (bills at face value on their real cadence);
        # index 0 keeps the classic monthly-equivalent header.
        if self._outlook_index > 0 and self._outlook_index < len(self._outlook):
            rows = outlook_stats_cells(self._outlook[self._outlook_index])
            # Future months carry no per-row backup yet, so the cells
            # stay plain there.
            cells = [
                self._stat_cell(label, value, caption, color)
                for label, value, caption, color in rows
            ]
        else:
            rows = budget_stats_cells(stats)
            cells = [
                self._stat_cell(
                    label,
                    value,
                    caption,
                    color,
                    on_tap=lambda e, k=label: self._open_stat_detail(k, e),
                )
                for label, value, caption, color in rows
            ]
        return ft.Container(
            content=ft.Row(cells, spacing=Theme.Spacing.LG),
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.LG, vertical=Theme.Spacing.SM
            ),
        )

    def _open_stat_detail(self, key: str, e: ft.ControlEvent) -> None:
        if self.page is not None:
            self.page.run_task(self._open_stat_detail_async, key, e)

    async def _open_stat_detail_async(self, key: str, e: ft.ControlEvent) -> None:
        """Rows for whichever cell was clicked. The verdict and Budgets
        build from the summary already on screen (zero fetch, cannot
        disagree with the strip); the rest come from one cached
        /budget/stat-details fetch."""
        stats = (self._summary or {}).get("stats", {})
        if key == "This month":
            self._stat_detail.open_at(
                e, "The month, line by line", equation_rows(stats)
            )
            return
        if key == "Budgets":
            buckets = {b["name"]: b for b in (self._summary or {}).get("buckets", [])}
            rows = [
                {
                    "label": line.get("category_name")
                    or line.get("payee_label")
                    or "Overall",
                    "value": line.get("allocated_amount", 0),
                    "caption": f"{_usd(line.get('spent_amount', 0))} spent",
                }
                for line in buckets.get("flexible", {}).get("lines", [])
            ]
            rows.sort(key=lambda r: -r["value"])
            self._stat_detail.open_at(e, "Limits you've set", rows)
            return
        if self._stat_details is None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            data = await api.get(
                "/api/v1/finance/budget/stat-details",
                params=self._account_filter.params(),
            )
            if not isinstance(data, dict):
                return
            self._stat_details = data
        details = self._stat_details
        if key == "Income":
            self._stat_detail.open_at(
                e, "Confirmed income", _captioned(details["income"])
            )
        elif key == "Bills":
            self._stat_detail.open_at(
                e,
                "Bills, monthly equivalent",
                _captioned(details["bills"]),
                footer="Non-monthly bills shown at their monthly share",
            )
        elif key == "Everything else":
            self._stat_detail.open_at(
                e,
                "Everything else",
                _captioned(details["everything_else"]),
                footer=f"{stat_window_label(details)} - spending no bill "
                "or limit covers",
            )

    def _month_pager(self) -> ft.Control:
        """The months ahead as one row: arrows page the header, the chips
        name each month's verdict - the October that breaks even is
        visible without going looking for it."""
        if not self._outlook:
            return ft.Container()

        def _page(delta: int) -> None:
            self._outlook_index = max(
                0, min(len(self._outlook) - 1, self._outlook_index + delta)
            )
            self._render()

        def _jump(index: int) -> None:
            self._outlook_index = index
            self._render()

        chips: list[ft.Control] = []
        for i, entry in enumerate(self._outlook):
            if i == 0:
                label = f"Now ${round(entry.get('start_balance', 0) / 100):,}"
                color = Theme.Colors.TEXT_SECONDARY
            else:
                label, color = outlook_chip(entry)
            selected = i == self._outlook_index
            chips.append(
                ft.Container(
                    content=SecondaryText(
                        label,
                        size=Theme.Typography.BODY_SMALL,
                        color=color,
                        weight=ft.FontWeight.W_600 if selected else None,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                    border_radius=Theme.Components.BUTTON_RADIUS,
                    border=ft.border.all(
                        1,
                        Theme.Colors.ACCENT if selected else Theme.Colors.BORDER_SUBTLE,
                    ),
                    on_click=lambda _e, i=i: _jump(i),
                    ink=True,
                )
            )
        return ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    icon_size=16,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Previous month",
                    on_click=lambda _e: _page(-1),
                ),
                *chips,
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    icon_size=16,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Next month",
                    on_click=lambda _e: _page(1),
                ),
            ],
            spacing=Theme.Spacing.XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        )

    def _stat_cell(
        self,
        label: str,
        value: str,
        caption: str,
        color: str | None = None,
        on_tap: Callable[[ft.ControlEvent], None] | None = None,
    ) -> ft.Control:
        cell = ft.Column(
            [
                SecondaryText(label.upper(), size=Theme.Typography.CAPTION),
                NumericText(
                    value,
                    size=22,
                    weight=Theme.Typography.WEIGHT_BOLD,
                    color=color or Theme.Colors.TEXT_PRIMARY,
                ),
                SecondaryText(caption, size=Theme.Typography.BODY_SMALL),
            ],
            spacing=2,
        )
        if on_tap is None:
            cell.expand = True
            return cell
        # on_tap_down, not on_click: the popup anchors at the tap's own
        # coordinates (the same mechanics every picker trigger uses).
        return ft.Container(
            content=cell,
            expand=True,
            ink=True,
            border_radius=Theme.Components.BUTTON_RADIUS,
            on_tap_down=on_tap,
            on_click=lambda _e: None,
            tooltip="Click for the breakdown",
        )
