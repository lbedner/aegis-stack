"""The goal editor dialog: create a goal, or edit its target and rule.

One mixin of ``BudgetPanel`` - state contract in ``base``. Split from
``goals_tab`` because the dialog is the biggest thing on that tab by far
and it grew a second picker (what the target is measured against).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    LabelText,
    SecondaryText,
    ThemedSwitch,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.debounce import Debouncer
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    contribution_preview,
    linkable_account_options,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.base import (
    BudgetPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    dollars_to_cents,
    target_note_copy,
)
from app.components.frontend.theme import AegisTheme as Theme

# Only accounts money is actually spent from can answer "months of what".
CASH_ACCOUNT_TYPES = frozenset({"checking", "savings", "cash"})


def _months_or_zero(raw: str) -> int:
    """The months field as an int, 0 when it is not a number. One parser
    for the preview and the save, so the dialog cannot refuse to preview
    a value it would happily store."""
    try:
        return int(float(raw.strip()))
    except ValueError:
        return 0


class GoalEditorMixin(BudgetPanelState):
    """Create and edit dialogs for one goal."""

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
        stats = (self._summary or {}).get("stats", {})
        income_total = stats.get("income_total", 0)
        current_target_rule = (goal or {}).get("target_rule", "fixed")
        current_scope = list((goal or {}).get("target_scope") or [])
        target_note = SecondaryText("", size=Theme.Typography.BODY_SMALL)
        debounce = Debouncer(self.page)
        factor_field = FormTextField(
            label="Months of expenses",
            value=str((goal or {}).get("target_factor") or ""),
            on_change=lambda _e: debounce.schedule(_refresh_target_note),
        )
        # Which accounts the months are measured on. A book with one
        # checking account never touches this; a book with a second one
        # would otherwise size a household fund on both.
        scope_dd = FormDropdown(
            label="Sized against",
            options=[("", "All accounts")],
            value=str(current_scope[0]) if current_scope else "",
            on_change=lambda _e: debounce.run_now(_refresh_target_note),
        )
        # Hosted, not mutated: the control wraps a stock dropdown, so a
        # list that arrives after the dialog opens replaces the whole
        # picker - the same move the funding picker makes below.
        scope_host = ft.Container(content=scope_dd)

        def _chosen_scope() -> list[int]:
            raw = (scope_host.content.value or "").strip()
            return [int(raw)] if raw else []

        async def _refresh_target_note() -> None:
            """Ask the server what the rule resolves to. The dialog never
            does this arithmetic itself - preview and saved goal come out
            of one function on one side of the wire."""
            from app.components.frontend.state.session_state import get_session_state

            rule = target_rule_dd.value or "fixed"
            months = (factor_field.value or "").strip()
            resolved: int | None = None
            # Parsed the way _save parses it, so the preview cannot say
            # "nothing to size against" about a value the form accepts.
            factor = _months_or_zero(months)
            if rule == "months_of_expenses" and factor > 0:
                params = f"factor={factor}&rule={rule}"
                for account_id in _chosen_scope():
                    params += f"&scope={account_id}"
                api = get_session_state(self.page).api_client
                data = await api.get(f"/api/v1/finance/goals/target-preview?{params}")
                if isinstance(data, dict):
                    resolved = data.get("target_amount")
            target_note.value = target_note_copy(rule, months, resolved)
            if target_note.page is not None:
                target_note.update()

        def _paint_target(rule: str) -> None:
            target_field.visible = rule == "fixed"
            factor_field.visible = rule == "months_of_expenses"
            scope_host.visible = rule == "months_of_expenses"
            for control in (target_field, factor_field, scope_host):
                if control.page is not None:
                    control.update()
            debounce.run_now(_refresh_target_note)

        target_rule_dd = FormDropdown(
            label="Target",
            options=[
                ("fixed", "A set amount"),
                ("months_of_expenses", "Months of expenses"),
            ],
            value=current_target_rule,
            on_change=lambda event: _paint_target(event.control.value or "fixed"),
        )
        target_field.visible = current_target_rule == "fixed"
        factor_field.visible = current_target_rule == "months_of_expenses"
        scope_host.visible = current_target_rule == "months_of_expenses"
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

            target_rule = target_rule_dd.value or "fixed"
            target = dollars_to_cents(target_field.value)
            factor: int | None = None
            if target_rule == "months_of_expenses":
                factor = _months_or_zero(factor_field.value or "")
                if not 0 < factor <= 120:
                    factor_field.set_error("A number of months, 1 to 120.")
                    return
            elif target is None or target <= 0:
                target_field.set_error("Every dream needs a number.")
                return
            kind = rule_dd.value or "fixed"
            monthly = dollars_to_cents(monthly_field.value)
            payload: dict[str, Any] = {
                "target_amount": target if target_rule == "fixed" else None,
                "target_rule": target_rule,
                "target_factor": factor,
                "target_scope": _chosen_scope() if target_rule != "fixed" else [],
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
                    target_rule_dd,
                    target_field,
                    factor_field,
                    target_note,
                    scope_host,
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
        if self.page:
            self.page.run_task(
                self._fill_target_scope, scope_host, _refresh_target_note
            )
        if creating and self.page:
            self.page.run_task(
                self._offer_linkable_accounts,
                link_host,
                name_host,
                auto_host,
                _install,
            )

    async def _fill_target_scope(
        self,
        scope_host: ft.Container,
        refresh: Callable[[], Awaitable[None]],
    ) -> None:
        """Offer this book's spending accounts alongside "All accounts",
        then draw the first preview. Fetched on open, like the funding
        picker: the account list must be current."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/finance/accounts")
        accounts = data.get("items", []) if isinstance(data, dict) else []
        options = [("", "All accounts")] + [
            (str(a["id"]), a["name"])
            for a in accounts
            if a.get("account_type") in CASH_ACCOUNT_TYPES
        ]
        current = scope_host.content
        scope_host.content = FormDropdown(
            label="Sized against",
            options=options,
            value=current.value or "",
            on_change=lambda _e: self.page.run_task(refresh),
        )
        if scope_host.page is not None:
            scope_host.update()
        await refresh()

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
