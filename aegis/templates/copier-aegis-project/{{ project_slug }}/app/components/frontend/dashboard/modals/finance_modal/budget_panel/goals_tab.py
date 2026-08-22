"""The Goals sub-tab: goal cards, pause, contribute, edit, linkable accounts.

One mixin of ``BudgetPanel`` - state contract in ``base``.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    PrimaryText,
    SecondaryText,
    WarningText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormTextField,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_lines_grid,
    savings_goal_card,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.goal_editor import (
    GoalEditorMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    dollars_to_cents,
    goal_shortfall_caption,
)
from app.components.frontend.theme import AegisTheme as Theme


class GoalsTabMixin(GoalEditorMixin):
    """The Goals sub-tab: goal cards, pause, contribute, edit, linkable accounts."""

    # -- Goals sub-tab -----------------------

    def _goals_section(self) -> ft.Control:
        """Goal cards on the budget-lines grid, or the dreams empty state."""
        new_button = PulseButton(
            on_click_callable=lambda: self._open_goal_editor(None),
            text="New goal",
            variant="teal",
            compact=True,
        )
        if not self._goals:
            return ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                PrimaryText("No goals yet."),
                                SecondaryText(
                                    "Name a dream, give it a number, and the "
                                    "month starts saving toward it."
                                ),
                                ft.Container(height=Theme.Spacing.SM),
                                new_button,
                            ],
                            spacing=Theme.Spacing.XS,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            tight=True,
                        ),
                        alignment=ft.alignment.center,
                        padding=Theme.Spacing.XL,
                    )
                ],
                expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
            )
        cards = [
            savings_goal_card(
                goal,
                on_contribute=(lambda g=goal: self._open_goal_contribute(g)),
                on_toggle_pause=(lambda g=goal: self._toggle_goal_pause(g)),
                on_edit=(lambda g=goal: self._open_goal_editor(g)),
                on_remove=(lambda g=goal: self._confirm_remove_goal(g)),
            )
            for goal in self._goals
        ]
        # Goals that ask for money the month does not have say so here.
        # Named, not clamped: the plan stays what the user set.
        shortfall = goal_shortfall_caption(
            (self._summary or {}).get("stats", {}).get("goals_shortfall", 0)
        )
        return ft.Column(
            [
                ft.Row([ft.Container(expand=True), new_button]),
                *(
                    [WarningText(shortfall, size=Theme.Typography.BODY_SMALL)]
                    if shortfall
                    else []
                ),
                budget_lines_grid(cards),
            ],
            spacing=Theme.Spacing.MD,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    async def _toggle_goal_pause(self, goal: dict[str, Any]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        status = "active" if goal.get("status") == "paused" else "paused"
        result = await api.patch(
            f"/api/v1/finance/goals/{goal['account_id']}", json={"status": status}
        )
        if not isinstance(result, dict):
            ErrorSnackBar(api.last_error or "Could not update the goal.").launch(
                self.page
            )
            return
        await self._load()

    def _confirm_remove_goal(self, goal: dict[str, Any]) -> None:
        linked = goal.get("funding") == "linked"
        ConfirmDialog(
            page=self.page,
            title="Remove goal",
            message=(
                f"Stop tracking {goal.get('name', 'this goal')} as a goal? "
                + (
                    "The account itself stays, untouched."
                    if linked
                    else "Its saved-so-far record goes with it."
                )
            ),
            confirm_text="Remove",
            destructive=True,
            on_confirm=lambda: self._remove_goal(goal),
        ).show()

    async def _remove_goal(self, goal: dict[str, Any]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/goals/{goal['account_id']}")
        await self._load()

    def _open_goal_contribute(self, goal: dict[str, Any]) -> None:
        """add money to a virtual goal; linked goals point at
        transfers (their contributions book themselves)."""
        if goal.get("funding") == "linked":
            ErrorSnackBar(
                "Linked goals count their own transfers - move money to "
                f"{goal.get('name', 'the account')} and it books itself."
            ).launch(self.page)
            return
        amount_field = FormTextField(label="Amount ($)", width=320)
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            cents = dollars_to_cents(amount_field.value)
            if cents is None or cents <= 0:
                amount_field.set_error("Enter a dollar amount.")
                return
            api = get_session_state(self.page).api_client
            result = await api.post(
                f"/api/v1/finance/goals/{goal['account_id']}/contribute",
                json={"amount": cents},
            )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not add that.").launch(self.page)
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title=f"Add to {goal.get('name', 'goal')}",
            body=ft.Column([amount_field], tight=True),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)
