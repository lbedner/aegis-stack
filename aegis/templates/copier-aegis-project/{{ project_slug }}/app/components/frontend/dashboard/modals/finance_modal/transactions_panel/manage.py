"""The account Manage menu: rename, reconcile, remove.

One mixin of ``TransactionsPanel`` - state contract in ``base``.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.property_details import (
    PropertyDetailsMixin,
    ValuationHistoryMixin,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date


class ManageAccountMixin(
    PropertyDetailsMixin, ValuationHistoryMixin, TransactionsPanelState
):
    """The account Manage menu: rename, reconcile, remove, and - on a
    property account - its purchase and valuation details."""

    # -- Account management ---------------------------------------------------

    def _open_rename(self, account: dict) -> None:
        value = {"name": account.get("name", "")}
        field = FormTextField(
            label="Account name",
            value=account.get("name", ""),
            on_change=lambda e: value.__setitem__(
                "name", (getattr(e.control, "value", "") or "").strip()
            ),
            width=360,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _save() -> None:
            dialog.open = False
            self.page.update()
            new_name = value["name"]
            if new_name and new_name != account.get("name"):
                await self._do_rename(account["id"], new_name)

        # ConfirmDialog's look but carrying a text field, which
        # ConfirmDialog doesn't support.
        dialog = StyledAlertDialog(
            title="Rename account",
            body=field,
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    def _open_reconcile(self, account: dict) -> None:
        """FIN-37: reconcile the register to a bank statement.

        Two presses of one button: the first computes the register-vs-
        statement difference (a pure read) and shows it; the second - with
        the same inputs - applies it as one transfer-flagged adjustment
        that never counts as spending. Changing either input drops back
        to the compute step.
        """
        from datetime import date as date_cls

        date_field = FormDateField(
            label="As of date", value=date_cls.today().isoformat(), width=380
        )
        balance_field = FormTextField(
            label="Actual balance ($)",
            hint="What the account really held on that date",
            width=380,
        )
        summary = ft.Column([], spacing=Theme.Spacing.XS, tight=True)
        state: dict[str, Any] = {"previewed": None}

        def _set_confirm(label: str) -> None:
            # PulseButton renders its label from a content Text built at
            # construction - repaint that, not just the stored attr.
            confirm.text = label
            confirm.content.value = label
            if confirm.page is not None:
                confirm.update()

        def _cents() -> int | None:
            raw = (balance_field.value or "").replace("$", "").replace(",", "")
            raw = raw.strip()
            if not raw:
                return None
            try:
                return round(float(raw) * 100)
            except ValueError:
                return None

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _submit() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            cents = _cents()
            if cents is None or not date_field.value:
                ErrorSnackBar(
                    "Enter the date and the balance the account really had."
                ).launch(self.page)
                return
            api = get_session_state(self.page).api_client
            payload = {
                "statement_date": date_field.value,
                "statement_balance": cents,
            }
            if state["previewed"] != (date_field.value, cents):
                result = await api.post(
                    f"/api/v1/finance/accounts/{account['id']}/reconcile",
                    json={**payload, "preview": True},
                )
                if not isinstance(result, dict):
                    ErrorSnackBar(
                        api.last_error or "Could not compute the difference."
                    ).launch(self.page)
                    return
                state["previewed"] = (date_field.value, cents)
                delta = result.get("delta", 0)
                sign = "+" if delta > 0 else "-"
                when = format_date(result.get("statement_date"))
                lines: list[ft.Control] = [
                    SecondaryText(
                        f"The app shows (through {when}): "
                        f"{_usd(result.get('register_balance', 0))}"
                    ),
                    SecondaryText(f"You say it was: {_usd(cents)}"),
                ]
                if delta == 0:
                    lines.append(
                        SecondaryText(
                            "They already match - nothing to fix.",
                            color=Theme.Colors.SUCCESS,
                        )
                    )
                    _set_confirm("Mark reconciled")
                else:
                    lines.append(
                        SecondaryText(
                            f"The fix: a {sign}{_usd(abs(delta))} adjustment",
                            color=Theme.Colors.WARNING,
                        )
                    )
                    lines.append(
                        SecondaryText(
                            (
                                f"Posting records {_usd(cents)} as this "
                                f"account's value on {when} - it has no "
                                "transactions to adjust."
                            )
                            if result.get("route") == "valuation"
                            else (
                                f"Posting adds one 'Balance adjustment' "
                                f"transaction dated {when}, bringing the "
                                f"account to {_usd(cents)}. It never counts "
                                "as spending."
                            ),
                            size=Theme.Typography.BODY_SMALL,
                        )
                    )
                    _set_confirm("Post adjustment")
                summary.controls = lines
                if summary.page is not None:
                    summary.update()
                return

            result = await api.post(
                f"/api/v1/finance/accounts/{account['id']}/reconcile",
                json=payload,
            )
            if not isinstance(result, dict):
                ErrorSnackBar(
                    api.last_error or "Could not reconcile the account."
                ).launch(self.page)
                return
            dialog.open = False
            self.page.update()
            SuccessSnackBar(
                f"{account.get('name', 'Account')} reconciled through "
                f"{format_date(result.get('reconciled_through'))}."
            ).launch(self.page)
            await self._load()
            if self._reload_accounts is not None:
                await self._reload_accounts(account["id"])

        confirm = PulseButton(
            on_click_callable=_submit,
            text="Check",
            variant="teal",
            compact=True,
        )
        dialog = StyledAlertDialog(
            title="Reconcile account",
            body=ft.Column(
                [date_field, balance_field, summary],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                confirm,
            ],
            width=440,
        )
        self.page.open(dialog)

    def _open_remove(self, account: dict) -> None:
        ConfirmDialog(
            page=self.page,
            title="Remove account",
            message=(
                f'Remove "{account.get("name", "")}"? It will be hidden from '
                "your accounts. Its history is kept and not deleted."
            ),
            confirm_text="Remove",
            destructive=True,
            on_confirm=lambda: self._do_remove(account["id"]),
        ).show()

    async def _do_rename(self, account_id: int, name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.patch(
            f"/api/v1/finance/accounts/{account_id}", json={"name": name}
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not rename the account.").launch(self.page)
            return
        SuccessSnackBar(f"Renamed to {name}.").launch(self.page)
        if self._reload_accounts is not None:
            await self._reload_accounts(account_id)

    async def _do_remove(self, account_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/accounts/{account_id}")
        SuccessSnackBar("Account removed.").launch(self.page)
        if self._reload_accounts is not None:
            await self._reload_accounts(None)
