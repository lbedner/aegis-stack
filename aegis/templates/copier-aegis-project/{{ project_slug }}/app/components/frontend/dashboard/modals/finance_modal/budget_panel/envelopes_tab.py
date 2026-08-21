"""The Envelopes sub-tab: allowance cards, move, edit, remove.

One mixin of ``BudgetPanel`` - state contract in ``base``.
"""

from __future__ import annotations

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
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_lines_grid,
    envelope_card,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel.base import (
    BudgetPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    dollars_to_cents,
)
from app.components.frontend.theme import AegisTheme as Theme


class EnvelopesTabMixin(BudgetPanelState):
    """The Envelopes sub-tab: allowance cards, move, edit, remove."""

    # -- Envelopes sub-tab ---------------------------------------------

    def _envelopes_section(self) -> ft.Control:
        new_button = PulseButton(
            on_click_callable=lambda: self._open_envelope_editor(None),
            text="New envelope",
            variant="teal",
            compact=True,
        )
        if not self._envelopes:
            return ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                PrimaryText("No envelopes yet."),
                                SecondaryText(
                                    "A running balance inside your real cash - "
                                    "an allowance, a repairs pot. Credit it, "
                                    "spend it down, watch it carry."
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
            envelope_card(
                env,
                on_spend=(lambda e=env: self._open_envelope_move(e, spend=True)),
                on_credit=(lambda e=env: self._open_envelope_move(e, spend=False)),
                on_edit=(lambda e=env: self._open_envelope_editor(e)),
                on_remove=(lambda e=env: self._confirm_remove_envelope(e)),
            )
            for env in self._envelopes
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

    def _open_envelope_move(self, envelope: dict[str, Any], *, spend: bool) -> None:
        """Spend from / add to an envelope: one amount, one optional note
        (the note is the history the kid reads later)."""
        verb = "Spend from" if spend else "Add to"
        amount_field = FormTextField(label="Amount ($)", width=320)
        note_field = FormTextField(
            label="Note (optional)", hint="Roblox, mowing the lawn...", width=320
        )
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
            action = "spend" if spend else "credit"
            result = await api.post(
                f"/api/v1/finance/envelopes/{envelope['account_id']}/{action}",
                json={
                    "amount": cents,
                    "note": (note_field.value or "").strip() or None,
                },
            )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not save that.").launch(
                    self.page
                )
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title=f"{verb} {envelope.get('name', 'envelope')}",
            body=ft.Column(
                [amount_field, note_field], spacing=Theme.Spacing.SM, tight=True
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
                    text="Spend" if spend else "Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    def _open_envelope_editor(self, envelope: dict[str, Any] | None) -> None:
        creating = envelope is None
        name_field = FormTextField(
            label="Name", value="" if creating else str(envelope.get("name", ""))
        )
        credit_field = FormTextField(
            label="Credit amount ($, optional)",
            value=(
                ""
                if creating or not envelope.get("monthly_credit")
                else f"{envelope['monthly_credit'] / 100:.2f}"
            ),
        )
        cadence_dd = FormDropdown(
            label="How often?",
            options=[("weekly", "Weekly"), ("monthly", "Monthly")],
            value=(envelope or {}).get("cadence", "monthly"),
        )
        seed_field = FormTextField(
            label="Starting balance ($, optional)",
            hint="Money it begins with",
        )
        auto_switch = ThemedSwitch(
            value=bool((envelope or {}).get("auto_credit")),
            scale=0.8,
        )
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            credit = dollars_to_cents(credit_field.value)
            if creating:
                name = (name_field.value or "").strip()
                if not name:
                    name_field.set_error("Name the envelope.")
                    return
                cadence = cadence_dd.value or "monthly"
                result = await api.post(
                    "/api/v1/finance/envelopes",
                    json={
                        "name": name,
                        "monthly_credit": credit,
                        "cadence": cadence,
                        "starting_balance": dollars_to_cents(seed_field.value) or 0,
                    },
                )
                if isinstance(result, dict) and auto_switch.value:
                    result = await api.patch(
                        f"/api/v1/finance/envelopes/{result['account_id']}",
                        json={
                            "monthly_credit": credit,
                            "auto_credit": True,
                            "cadence": cadence,
                        },
                    )
            else:
                result = await api.patch(
                    f"/api/v1/finance/envelopes/{envelope['account_id']}",
                    json={
                        "monthly_credit": credit,
                        "auto_credit": bool(auto_switch.value),
                        "cadence": cadence_dd.value or "monthly",
                    },
                )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not save that.").launch(
                    self.page
                )
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title="New envelope" if creating else f"Edit {envelope.get('name', '')}",
            body=ft.Column(
                [
                    name_field,
                    *([seed_field] if creating else []),
                    credit_field,
                    cadence_dd,
                    ft.Row(
                        [auto_switch, LabelText("Credit it automatically")],
                        spacing=Theme.Spacing.SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
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
            width=420,
        )
        self.page.open(dialog)

    def _confirm_remove_envelope(self, envelope: dict[str, Any]) -> None:
        ConfirmDialog(
            page=self.page,
            title="Remove envelope",
            message=(
                f"Remove {envelope.get('name', 'this envelope')}? Its balance "
                "record goes with it."
            ),
            confirm_text="Remove",
            destructive=True,
            on_confirm=lambda: self._remove_envelope(envelope),
        ).show()

    async def _remove_envelope(self, envelope: dict[str, Any]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/envelopes/{envelope['account_id']}")
        await self._load()
