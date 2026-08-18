"""The budget panel core: load, render, the stats strip and month pager.

The four content areas live in sibling mixins (``suggestions``,
``lines_tab``, ``goals_tab``, ``envelopes_tab``); this module owns the
state, the constructor, and the load/render spine they call into.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    NumericText,
    SecondaryText,
    SectionCard,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_stats_cells,
    outlook_chip,
    outlook_stats_cells,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.base import (
    BudgetPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.envelopes_tab import (
    EnvelopesTabMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.goals_tab import (
    GoalsTabMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.lines_tab import (
    LinesTabMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.suggestions import (
    SuggestionsMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.finance_modal.stat_details import (
    StatDetailPopup,
    _captioned,
    equation_rows,
    stat_window_label,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    EmptyStatePlaceholder,
)
from app.components.frontend.theme import AegisTheme as Theme


class BudgetPanel(
    SuggestionsMixin,
    LinesTabMixin,
    GoalsTabMixin,
    EnvelopesTabMixin,
    BudgetPanelState,
):
    """Budget tab: a natural-language goal box, a 4-cell stats strip, then
    three sections.
    Fixed/Non-monthly are detected recurring commitments shown for
    CONTEXT ONLY - an earlier version gave every one of them (including
    the mortgage) a spend-vs-allocation status the same as a real budget
    line, which read as "you're over budget on your own mortgage". These
    read a variance-vs-last-month signal instead (``status_dot``, never
    critical) and have no remove/edit action - that's Bills & Income's
    job. Flexible is the actual budget: limits chosen by category or
    payee, by typed goal or by hand, each with a real spend-vs-allocation
    status and a remove action.
    The goal box mirrors ``UncategorizedPanel``'s review-before-commit
    shape: ``POST /budget/goal`` only computes a suggestion (accept/reject
    row, same interaction as ``_suggested_cell``); accepting it is a
    separate ``POST /budget/lines`` call, same split as auto-categorize's
    suggest-then-apply.
    """

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener, expand=True)
        self._categories: list[tuple[str, str]] = []
        self._summary: dict[str, Any] | None = None
        # One shared popup for all five cells (see StatDetailPopup), and
        # one fetch of the per-row details behind it - cleared per load
        # so it always matches what the cells show.
        self._stat_detail = StatDetailPopup()
        self._stat_details: dict[str, Any] | None = None
        self._goal_suggestion: dict[str, Any] | None = None
        # Bills are CONTEXT here, not the budget - and there are 76 of
        # them. Shown by default they bury the handful of limits you
        # actually set, which is the only part of this page you act on.
        self._show_commitments = False
        self._suggestions: list[dict[str, Any]] = []
        self._dismissed_suggestions: list[dict[str, Any]] = []
        self._show_dismissed = False
        self._suggestion_selection: set[int] = set()

        self._goal_field = FormTextField(
            label="",
            show_label=False,
            hint='e.g. "I wanna cut back on Starbucks"',
        )
        self._goal_result = ft.Container()
        self._stats = ft.Container()

        goal_card = SectionCard(
            title="Set a goal in plain English",
            body=ft.Column(
                [
                    ft.Row(
                        [
                            self._goal_field,
                            PulseButton(
                                on_click_callable=self._submit_goal,
                                text="Set budget",
                                compact=True,
                            ),
                        ],
                        spacing=Theme.Spacing.SM,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    self._goal_result,
                ],
                spacing=Theme.Spacing.SM,
            ),
            body_padding=Theme.Spacing.MD,
        )

        # The goal box is built but NOT mounted. It is a good idea with
        # nothing behind it yet: a full-width empty input at the top of
        # the page, above the numbers, asking to be typed into before
        # there is any budget to steer. The stats strip earns its place
        # (it reads even at zero), so that stays. Re-add ``goal_card``
        # here when the parse-then-accept flow is worth the real estate.
        self._goal_card = goal_card
        # Sub-tabs, one scroll context each. With suggestions ON the
        # limits page, its table scrolled inside a page that also
        # scrolled - two nested scrollbars fighting over the wheel. Each
        # tab now owns exactly one.
        self._subtab_index = 0
        self._goals: list[dict[str, Any]] = []
        self._envelopes: list[dict[str, Any]] = []
        self._outlook: list[dict[str, Any]] = []
        self._outlook_index = 0
        self._budget_tabs = PulseTabs(
            tabs=[
                ft.Tab(text="Limits"),
                ft.Tab(text="Suggested"),
                ft.Tab(text="Goals"),
                ft.Tab(text="Envelopes"),
            ],
            selected_index=0,
            expand=False,
            on_change=self._on_subtab_change,
        )
        self._body = ft.Container(expand=True)
        # The explanatory sentence rides an info icon instead of its own
        # line, and the month pager shares the title's row - together
        # that returns two rows of height to the tab's actual content.
        self._pager_slot = ft.Container()
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        H3Text("Does the month work?"),
                        ft.Icon(
                            ft.Icons.INFO_OUTLINE,
                            size=16,
                            color=Theme.Colors.TEXT_SECONDARY,
                            tooltip=(
                                "Your plan checked against how you actually "
                                "spend, and where that leaves your balance "
                                "in the months ahead"
                            ),
                        ),
                        ft.Container(expand=True),
                        self._pager_slot,
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._stats,
                self._budget_tabs,
                self._body,
                self._stat_detail,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def _on_subtab_change(self, event: ft.ControlEvent) -> None:
        self._subtab_index = int(event.control.selected_index or 0)
        # Paint the cached data instantly, then refetch behind it - the
        # suggestions and commitment totals both react to what the other
        # tabs just did.
        self._render()
        if self.page:
            self.page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state
        from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

        api = get_session_state(self.page).api_client
        if not self._categories:
            cat_data = await api.get("/api/v1/finance/categories/options", cache_ttl=30)
            cat_items = cat_data.get("items", []) if isinstance(cat_data, dict) else []
            self._categories = [
                (str(c["id"]), c["name"])
                for c in cat_items
                if str(c.get("name", "")).lower() not in UNCATEGORIZED_CATEGORY_NAMES
            ]
        # An explicit empty selection ("Remove all") means literally nothing,
        # not "no filter" - AccountFilter.params() is never called in this
        # state (see its own docstring), so the fetch is skipped outright,
        # same as OverviewTab's own charts and UncategorizedPanel do.
        data: dict[str, Any] = (
            {"buckets": [], "stats": {}, "trims": []}
            if self._account_filter.is_empty
            else await api.get(
                "/api/v1/finance/budget/summary", params=self._account_filter.params()
            )
        )
        self._summary = data if isinstance(data, dict) else None
        self._stat_details = None
        goals = await api.get("/api/v1/finance/goals")
        self._goals = goals.get("items", []) if isinstance(goals, dict) else []
        envelopes = await api.get("/api/v1/finance/envelopes")
        self._envelopes = (
            envelopes.get("items", []) if isinstance(envelopes, dict) else []
        )
        outlook = (
            {"items": []}
            if self._account_filter.is_empty
            else await api.get(
                "/api/v1/finance/budget/outlook",
                params={"months": 6, **self._account_filter.params()},
            )
        )
        self._outlook = outlook.get("items", []) if isinstance(outlook, dict) else []
        picks = await api.get("/api/v1/finance/budget/suggestions")
        self._suggestions = picks.get("items", []) if isinstance(picks, dict) else []
        self._dismissed_suggestions = (
            picks.get("dismissed", []) if isinstance(picks, dict) else []
        )
        # A reload rebuilds the table unchecked; stale indices must not
        # survive into the fresh one.
        self._suggestion_selection = set()
        self._render()

    def _render(self) -> None:
        if not self._summary:
            self._body.content = EmptyStatePlaceholder("Could not load the budget.")
            if self.page:
                self.update()
            return
        buckets = {b["name"]: b for b in self._summary.get("buckets", [])}
        self._stats.content = self._stats_strip(self._summary.get("stats", {}))
        self._pager_slot.content = self._month_pager()
        # Your budget first. The commitment sections are collapsed behind
        # one line so the page opens on what you set, not on 76 bills that
        # Bills & Income already owns.
        label = (
            f"Suggested ({len(self._suggestions)})"
            if self._suggestions
            else "Suggested"
        )
        if self._budget_tabs.tabs[1].text != label:
            self._budget_tabs.tabs[1].text = label
            if self._budget_tabs.page:
                self._budget_tabs.update()
        goals_label = f"Goals ({len(self._goals)})" if self._goals else "Goals"
        if self._budget_tabs.tabs[2].text != goals_label:
            self._budget_tabs.tabs[2].text = goals_label
            if self._budget_tabs.page:
                self._budget_tabs.update()
        envelopes_label = (
            f"Envelopes ({len(self._envelopes)})" if self._envelopes else "Envelopes"
        )
        if self._budget_tabs.tabs[3].text != envelopes_label:
            self._budget_tabs.tabs[3].text = envelopes_label
            if self._budget_tabs.page:
                self._budget_tabs.update()
        if self._subtab_index == 3:
            self._body.content = self._envelopes_section()
            if self.page:
                self.update()
            return
        if self._subtab_index == 2:
            self._body.content = self._goals_section()
            if self.page:
                self.update()
            return
        if self._subtab_index == 1:
            # Dismissals keep the section alive even with zero live
            # suggestions - restoring one has to happen somewhere.
            self._body.content = (
                self._suggestions_section()
                if self._suggestions or self._dismissed_suggestions
                else EmptyStatePlaceholder(
                    message="Nothing to suggest - your steady spending is "
                    "covered by bills or budgeted already."
                )
            )
            if self.page:
                self.update()
            return
        children: list[ft.Control] = []
        trims = self._summary.get("trims") or []
        if trims:
            children.append(self._trims_section(trims))
        children.append(self._flexible_section(buckets.get("flexible")))
        children.append(self._commitments_toggle(buckets))
        if self._show_commitments:
            children.append(
                self._commitment_section(
                    "Fixed",
                    "Recurring, same amount every cycle - nothing to decide here",
                    buckets.get("fixed"),
                    "Not budgeted, just shown",
                )
            )
            children.append(
                self._commitment_section(
                    "Non-monthly",
                    "Real, recurring, just not every cycle - set aside a "
                    "monthly slice so it doesn't ambush you",
                    buckets.get("non_monthly"),
                    "Set aside",
                )
            )
        self._body.content = ft.Column(
            children,
            spacing=Theme.Spacing.LG,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        if self.page:
            self.update()

    # -- stats strip -----------------------------------------------------

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
        disagree with the strip); Income/Bills/Everything else come from
        one cached /budget/stat-details fetch."""
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
                footer=(
                    f"{stat_window_label(details)} - observed spending "
                    "no bill or limit covers"
                ),
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
