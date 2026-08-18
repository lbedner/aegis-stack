"""Budget suggestions: the auto-detected lines, dismissals, and the natural-language goal parser.

One mixin of ``BudgetPanel`` - state contract in ``base``.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    NumericText,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.pickers import BulkActionTrigger
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.controls.table import (
    TableCellText,
    TableNameText,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_suggestion_caption,
    goal_suggestion_message,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.base import (
    BudgetPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _DENSE_ROW_HEIGHT,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.theme import AegisTheme as Theme


class SuggestionsMixin(BudgetPanelState):
    """Budget suggestions: the auto-detected lines, dismissals, and the natural-language goal parser."""

    def _suggestions_section(self) -> ft.Control:
        """Every line your own spending implies - all of them, not a top
        five. Knowing what your budget is ABOUT means seeing the $20 gym
        alongside the $1,399 groceries; the tail is where the surprises
        live, and hiding it would just be another number nobody chose.

        Rows use the house select-many pattern (checkboxes + bulk verbs),
        so accepting or declining a batch is one gesture - and a declined
        suggestion stays declined across months until restored here.
        """
        total = sum(p.get("suggested_amount", 0) for p in self._suggestions)

        async def _accept_all() -> None:
            await self._accept_suggestions(list(self._suggestions))

        def _checked_picks() -> list[dict[str, Any]]:
            return [
                self._suggestions[i]
                for i in sorted(self._suggestion_selection)
                if i < len(self._suggestions)
            ]

        async def _use_checked() -> None:
            picks = _checked_picks()
            if picks:
                await self._accept_suggestions(picks)

        async def _dismiss_checked() -> None:
            picks = _checked_picks()
            if picks:
                await self._dismiss_suggestions(
                    [p["category_id"] for p in picks if p.get("category_id")]
                )

        use_checked = BulkActionTrigger(
            on_tap=lambda e: e.page.run_task(_use_checked),
            label="Use",
            tooltip="Add every checked suggestion as a budget line",
        )
        dismiss_checked = BulkActionTrigger(
            on_tap=lambda e: e.page.run_task(_dismiss_checked),
            label="Dismiss",
            tooltip=(
                "Hide every checked suggestion. It stays hidden across "
                "months until restored below"
            ),
            variant="stop",
        )

        def _on_selection_change(indices: set[int]) -> None:
            self._suggestion_selection = set(indices)
            use_checked.set_count(len(indices))
            dismiss_checked.set_count(len(indices))

        rows = [
            [
                TableNameText(p.get("category_name") or "Uncategorized"),
                NumericText(_usd(p.get("suggested_amount", 0))),
                SecondaryText(budget_suggestion_caption(p)),
            ]
            for p in self._suggestions
        ]
        children: list[ft.Control] = []
        if self._suggestions:
            children.append(
                DataTable(
                    columns=[
                        DataTableColumn("Category", hideable=False),
                        DataTableColumn("Per month", width=120, alignment="right"),
                        DataTableColumn("Based on", width=220, style="secondary"),
                    ],
                    rows=rows,
                    row_padding=6,
                    item_extent=_DENSE_ROW_HEIGHT,
                    # The table IS the tab: it fills the panel and is
                    # the only thing that scrolls - the nested
                    # table-inside-scrolling-page arrangement fought
                    # over the wheel.
                    expand=True,
                    selectable=True,
                    on_selection_change=_on_selection_change,
                )
            )
        children.extend(self._dismissed_suggestion_rows())
        # No SectionCard: the DataTable already draws its own card, and a
        # card around a card read as a table within a table. One bare
        # action strip above it - summary left, every verb right - at a
        # FIXED height, so the bulk chips appearing on first check don't
        # jump the table down.
        summary = (
            f"{len(self._suggestions)} categories, {_usd(total)}/month · "
            "median of the last 6 complete months, skipping transfers "
            "and anything a bill already covers"
            if self._suggestions
            else "Nothing to suggest. Dismissed suggestions are below."
        )
        strip = ft.Container(
            content=ft.Row(
                [
                    ft.Container(content=SecondaryText(summary), expand=True),
                    dismiss_checked,
                    use_checked,
                    *(
                        [
                            PulseButton(
                                on_click_callable=_accept_all,
                                text=f"Use all {len(self._suggestions)}",
                                compact=True,
                            )
                        ]
                        if self._suggestions
                        else []
                    ),
                ],
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=44,
        )
        return ft.Column(
            [strip, *children],
            spacing=Theme.Spacing.SM,
            expand=True,
        )

    def _dismissed_suggestion_rows(self) -> list[ft.Control]:
        """The "N dismissed · Show" affordance and, when open, the list of
        declined suggestions with a Restore per row - reversibility
        without DB surgery."""
        if not self._dismissed_suggestions:
            return []
        count = len(self._dismissed_suggestions)

        def _toggle(_e: ft.ControlEvent) -> None:
            self._show_dismissed = not self._show_dismissed
            self._render()

        def _restore(category_id: int):
            async def _run() -> None:
                await self._restore_suggestions([category_id])

            return _run

        word = "Hide" if self._show_dismissed else "Show"
        controls: list[ft.Control] = [
            ft.Container(
                content=SecondaryText(
                    f"{count} dismissed  ·  {word}",
                    size=Theme.Typography.BODY_SMALL,
                ),
                on_click=_toggle,
                ink=True,
                border_radius=Theme.Components.BUTTON_RADIUS,
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
            )
        ]
        if self._show_dismissed:
            controls.extend(
                ft.Row(
                    [
                        ft.Container(
                            content=SecondaryText(
                                d.get("category_name") or "Uncategorized"
                            ),
                            expand=True,
                        ),
                        PulseButton(
                            on_click_callable=_restore(d.get("category_id")),
                            text="Restore",
                            variant="muted",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for d in self._dismissed_suggestions
            )
        return controls

    async def _dismiss_suggestions(self, category_ids: list[int]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/suggestions/dismiss",
            json={"category_ids": category_ids},
        )
        if not isinstance(result, dict):
            ErrorSnackBar(
                api.last_error or "Could not dismiss those suggestions."
            ).launch(self.page)
            return
        count = len(category_ids)
        SuccessSnackBar(
            f"Dismissed {count} suggestion{'s' if count != 1 else ''}."
        ).launch(self.page)
        await self._load()

    async def _restore_suggestions(self, category_ids: list[int]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/suggestions/restore",
            json={"category_ids": category_ids},
        )
        if not isinstance(result, dict):
            ErrorSnackBar(
                api.last_error or "Could not restore that suggestion."
            ).launch(self.page)
            return
        await self._load()

    async def _accept_suggestions(self, picks: list[dict[str, Any]]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        saved = 0
        for pick in picks:
            result = await api.post(
                "/api/v1/finance/budget/lines",
                json={
                    "category_id": pick.get("category_id"),
                    "allocated_amount": pick.get("suggested_amount"),
                },
            )
            if isinstance(result, dict):
                saved += 1
        if not saved:
            ErrorSnackBar("Could not add those budget lines.").launch(self.page)
            return
        SuccessSnackBar(
            f"Added {saved} budget line{'s' if saved != 1 else ''}."
        ).launch(self.page)
        await self._load()

    # -- goal box ------------------------------------------------------

    async def _submit_goal(self) -> None:
        text = self._goal_field.value.strip()
        if not text:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post("/api/v1/finance/budget/goal", json={"text": text})
        if not isinstance(result, dict) or not result.get("matched"):
            message = (
                "Couldn't find a category or recent payee matching that - "
                "try naming one directly, or add a budget line manually."
                if isinstance(result, dict)
                else api.last_error or "Could not parse that."
            )
            ErrorSnackBar(message or "No match found.").launch(self.page)
            self._goal_suggestion = None
            self._goal_result.content = None
            if self.page:
                self.update()
            return
        self._goal_suggestion = result
        self._goal_result.content = self._suggestion_row(result)
        if self.page:
            self.update()

    def _suggestion_row(self, suggestion: dict[str, Any]) -> ft.Control:
        amount = suggestion.get("suggested_limit") or 0
        return ft.Row(
            [
                Tag("PARSED", color=Theme.Colors.ACCENT),
                ft.Container(
                    content=TableCellText(goal_suggestion_message(suggestion)),
                    expand=True,
                ),
                PulseButton(
                    on_click_callable=self._dismiss_goal,
                    text="Adjust",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=self._accept_goal,
                    text=f"Confirm ${amount / 100:,.0f}",
                    variant="teal",
                    compact=True,
                ),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def _accept_goal(self) -> None:
        suggestion = self._goal_suggestion
        if suggestion is None:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/lines",
            json={
                "category_id": suggestion.get("category_id"),
                "payee_key": suggestion.get("payee_key"),
                "payee_label": suggestion.get("payee_label"),
                "allocated_amount": suggestion.get("suggested_limit") or 0,
            },
        )
        if result is None:
            ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
            return
        SuccessSnackBar("Budget line set.").launch(self.page)
        self._goal_suggestion = None
        self._goal_result.content = None
        self._goal_field.value = ""
        await self._load()

    async def _dismiss_goal(self) -> None:
        self._goal_suggestion = None
        self._goal_result.content = None
        if self.page:
            self.update()
