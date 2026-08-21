"""The Goals sub-tab: goal cards, pause, contribute, edit, linkable accounts.

One mixin of ``BudgetPanel`` - state contract in ``base``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    LabelText,
    PrimaryText,
    SecondaryText,
    ThemedSwitch,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_lines_grid,
    contribution_preview,
    linkable_account_options,
    savings_goal_card,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.base import (
    BudgetPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    dollars_to_cents,
)
from app.components.frontend.theme import AegisTheme as Theme


class GoalsTabMixin(BudgetPanelState):
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
        return ft.Column(
            [
                ft.Row([ft.Container(expand=True), new_button]),
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

    def _open_goal_editor(self, goal: dict[str, Any] | None) -> None:
        """create (virtual by default, or link an existing account)
        or edit targets. All existing form controls."""
        creating = goal is None
        name_field = FormTextField(
            label="Name", value="" if creating else str(goal.get("name", ""))
        )
        target_field = FormTextField(
            label="Target ($)",
            value="" if creating else f"{goal['target_amount'] / 100:.2f}",
        )
        date_field = FormDateField(
            label="Target date (optional)",
            value=(goal or {}).get("target_date") or "",
        )
        monthly_field = FormTextField(
            label="Monthly amount ($, optional)",
            value=(
                ""
                if creating or not goal.get("monthly_contribution")
                else f"{goal['monthly_contribution'] / 100:.2f}"
            ),
        )
        income_total = (self._summary or {}).get("stats", {}).get("income_total", 0)
        preview = SecondaryText("", size=Theme.Typography.BODY_SMALL)

        def _percent_typed(event: ft.ControlEvent) -> None:
            preview.value = contribution_preview(
                "percent_income",
                getattr(event.control, "value", "") or "",
                income_total=income_total,
            )
            if preview.page is not None:
                preview.update()

        percent_field = FormTextField(
            label="Percent of income (%)",
            value=(
                ""
                if creating or not goal.get("contribution_pct_bps")
                else f"{goal['contribution_pct_bps'] / 100:g}"
            ),
            on_change=_percent_typed,
        )
        monthly_host = ft.Container(content=monthly_field)
        percent_host = ft.Container(content=percent_field, visible=False)
        current_kind = (goal or {}).get("contribution_kind", "fixed")

        def _paint_rule(kind: str) -> None:
            monthly_host.visible = kind == "fixed"
            percent_host.visible = kind == "percent_income"
            preview.value = contribution_preview(
                kind, percent_field.value, income_total=income_total
            )
            for control in (monthly_host, percent_host, preview):
                if control.page is not None:
                    control.update()

        def _rule_changed(event: ft.ControlEvent) -> None:
            _paint_rule(event.control.value or "fixed")

        rule_dd = FormDropdown(
            label="Contribute how?",
            options=[
                ("fixed", "Fixed amount"),
                ("percent_income", "% of income"),
                ("surplus", "Whatever's left each month"),
            ],
            value=current_kind,
            on_change=_rule_changed,
        )
        monthly_host.visible = current_kind == "fixed"
        percent_host.visible = current_kind == "percent_income"
        preview.value = contribution_preview(
            current_kind, percent_field.value, income_total=income_total
        )
        # Label as its own control beside the switch, not ft.Switch's
        # built-in label: the built-in renders Material's small caption
        # next to a 0.5-scaled knob and the whole row reads miniature.
        # LabelText is the same widget the field labels above it use, and
        # 0.8 is the scale the voice tab's dialog switches settled on.
        auto_switch = ThemedSwitch(
            value=bool((goal or {}).get("auto_contribute")),
            scale=0.8,
        )
        # Only virtual goals auto-book - a linked goal's real transfers
        # are its bookings. Hidden, not disabled: an inert switch invites
        # a support question the row can't answer.
        auto_host = ft.Container(
            content=ft.Row(
                [auto_switch, LabelText("Book it automatically on the 1st")],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=creating or (goal or {}).get("funding") != "linked",
        )
        # Funding picker only at creation - a goal doesn't change species.
        link_dd: FormDropdown | None = None
        link_host = ft.Container(visible=False)
        name_host = ft.Container(content=name_field)
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            target = dollars_to_cents(target_field.value)
            if target is None or target <= 0:
                target_field.set_error("Every dream needs a number.")
                return
            kind = rule_dd.value or "fixed"
            monthly = dollars_to_cents(monthly_field.value)
            payload: dict[str, Any] = {
                "target_amount": target,
                "target_date": date_field.value or None,
                "monthly_contribution": monthly if kind == "fixed" else None,
                "contribution_kind": kind,
            }
            if kind == "percent_income":
                raw_pct = (percent_field.value or "").replace("%", "").strip()
                try:
                    bps = round(float(raw_pct) * 100)
                except ValueError:
                    bps = 0
                if not 0 < bps <= 10_000:
                    percent_field.set_error("A percent between 0 and 100.")
                    return
                payload["contribution_pct_bps"] = bps
            payload["auto_contribute"] = bool(auto_switch.value)
            api = get_session_state(self.page).api_client
            if creating:
                choice = link_dd.value if link_dd is not None else "virtual"
                if choice == "virtual":
                    name = (name_field.value or "").strip()
                    if not name:
                        name_field.set_error("Name the goal.")
                        return
                    payload["name"] = name
                else:
                    payload["account_id"] = int(choice)
                    payload["auto_contribute"] = False
                result = await api.post("/api/v1/finance/goals", json=payload)
            else:
                result = await api.patch(
                    f"/api/v1/finance/goals/{goal['account_id']}", json=payload
                )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not save the goal.").launch(
                    self.page
                )
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title="New goal" if creating else f"Edit {goal.get('name', 'goal')}",
            body=ft.Column(
                [
                    link_host,
                    name_host,
                    target_field,
                    date_field,
                    rule_dd,
                    monthly_host,
                    percent_host,
                    preview,
                    auto_host,
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Create" if creating else "Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=460,
        )

        def _install(dd: FormDropdown) -> None:
            nonlocal link_dd
            link_dd = dd

        self.page.open(dialog)
        if creating and self.page:
            self.page.run_task(
                self._offer_linkable_accounts,
                link_host,
                name_host,
                auto_host,
                _install,
            )

    async def _offer_linkable_accounts(
        self,
        link_host: ft.Container,
        name_host: ft.Container,
        auto_host: ft.Container,
        install: Callable[[FormDropdown], None],
    ) -> None:
        """Fetch accounts and, when any are linkable, add the funding
        picker to the open create dialog. Fetched on open, not at tab
        build - the list must be current, and most opens never link."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/finance/accounts")
        accounts = data.get("items", []) if isinstance(data, dict) else []
        options = linkable_account_options(accounts)
        if not options:
            return

        def _mode_changed(event: ft.ControlEvent) -> None:
            virtual = event.control.value == "virtual"
            name_host.visible = virtual
            auto_host.visible = virtual
            for control in (name_host, auto_host):
                if control.page is not None:
                    control.update()

        dd = FormDropdown(
            label="Fund it how?",
            options=[("virtual", "Save toward it here (virtual)")]
            + [(key, f"Track {label}") for key, label in options],
            value="virtual",
            on_change=_mode_changed,
        )
        install(dd)
        link_host.content = dd
        link_host.visible = True
        if link_host.page is not None:
            link_host.update()
