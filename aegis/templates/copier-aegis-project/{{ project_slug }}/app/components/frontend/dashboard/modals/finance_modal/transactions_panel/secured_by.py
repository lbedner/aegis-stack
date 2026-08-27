"""Secured by: which property stands behind a liability.

One mixin of ``TransactionsPanel`` - state contract in ``base``. Reached
from the account header's Manage menu, offered only on liability
accounts. Stores what the user CONFIRMS (the assistant refuses to guess
lien priority); equity and LTV derive from the link at read time,
everywhere accounts are read.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import FormDropdown, FormTextField
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.theme import AegisTheme as Theme

_NONE_VALUE = "none"


def secured_by_payload(
    property_id: int | None, lien_position: str | None
) -> dict[str, Any]:
    """Picker values -> PATCH body (pure).

    No property selected means UNLINK, and the position clears with it -
    a lien position on nothing is not a fact. A blank position while
    linking stays None; the API defaults it to 1 (first mortgage).
    """
    if property_id is None:
        return {"secured_by_account_id": None, "lien_position": None}
    text = (lien_position or "").strip()
    return {
        "secured_by_account_id": property_id,
        "lien_position": int(text) if text else None,
    }


class SecuredByMixin(TransactionsPanelState):
    """The Manage menu's Secured by dialog."""

    def _open_secured_by(self, account: dict) -> None:
        self.page.run_task(self._open_secured_by_dialog, account)

    async def _open_secured_by_dialog(self, account: dict) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        listing = await api.get("/api/v1/finance/accounts")
        if not isinstance(listing, dict):
            # A failed fetch is not "you have no properties" - say what
            # actually happened, like every other panel flow.
            ErrorSnackBar(api.last_error or "Could not load your accounts.").launch(
                self.page
            )
            return
        rows = listing.get("items", [])
        properties = [r for r in rows if r.get("account_type") == "property"]
        if not properties:
            ErrorSnackBar("Add a property account first.").launch(self.page)
            return

        liability = account.get("liability") or {}
        current = liability.get("secured_by_account_id")
        picker = FormDropdown(
            label="Secured by",
            options=[(_NONE_VALUE, "Not secured")]
            + [(str(r["id"]), r["name"]) for r in properties],
            value=str(current) if current is not None else _NONE_VALUE,
            width=260,
            variant="pulse",
        )
        position = FormTextField(
            label="Lien position",
            value=str(liability.get("lien_position") or ""),
            hint="1 = first mortgage",
            width=150,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _save() -> None:
            chosen = picker.value
            property_id = None if chosen in (None, _NONE_VALUE) else int(chosen)
            try:
                payload = secured_by_payload(property_id, position.value)
            except ValueError:
                ErrorSnackBar("Lien position must be a number.").launch(self.page)
                return
            dialog.open = False
            self.page.update()
            await self._save_secured_by(account["id"], payload)

        dialog = StyledAlertDialog(
            title="Secured by",
            body=ft.Column(
                [
                    SecondaryText(
                        "Which property stands behind this balance. Equity "
                        "and LTV are computed from the link - nothing is "
                        "stored twice."
                    ),
                    ft.Row([picker, position], spacing=Theme.Spacing.SM),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
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
            width=480,
        )
        self.page.open(dialog)

    async def _save_secured_by(self, account_id: int, payload: dict[str, Any]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.patch(
            f"/api/v1/finance/accounts/{account_id}/secured-by", json=payload
        )
        if not isinstance(response, dict):
            ErrorSnackBar(api.last_error or "Could not save the link.").launch(
                self.page
            )
            return
        SuccessSnackBar("Secured-debt link saved.").launch(self.page)
        if self._reload_accounts is not None:
            await self._reload_accounts()
