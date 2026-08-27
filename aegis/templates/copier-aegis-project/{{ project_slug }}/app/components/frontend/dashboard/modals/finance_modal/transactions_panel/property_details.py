"""Property details: how a property was bought, and where its value came from.

One mixin of ``TransactionsPanel`` - state contract in ``base``. Reached
from the account header's Manage menu, which offers it only on property
accounts.

The dialog writes through ``PATCH /accounts/{id}/property``, whose Pydantic
contract is the real validation boundary; this side only has to convert
dollars to cents honestly and refuse to invent a figure the user left blank.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.theme import AegisTheme as Theme

VALUATION_SOURCES = (
    ("user", "Your estimate"),
    ("automated", "Automated estimate"),
    ("broker", "Broker opinion"),
    ("appraisal", "Appraisal"),
)
PROPERTY_KINDS = (
    ("primary", "Primary residence"),
    ("rental", "Rental"),
    ("vacation", "Vacation home"),
    ("land", "Land"),
    ("other", "Other"),
)


def _cents(value: str | None) -> int | None:
    """Dollars as typed -> cents, or None when left blank.

    Blank means unknown and must stay unknown: a 0 would claim the house
    was free, and every equity figure downstream would inherit it.
    """
    text = (value or "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    return round(float(text) * 100)


def property_payload(
    *,
    purchase_price: str | None = None,
    purchase_date: date | None = None,
    down_payment: str | None = None,
    property_kind: str = "primary",
    valuation_source: str = "user",
    valuation_as_of: date | None = None,
    include_in_net_worth: bool = True,
    address_label: str | None = None,
) -> dict[str, Any]:
    """Form values -> PATCH body (pure). Raises ValueError on a bad amount."""
    return {
        "property_kind": property_kind,
        "purchase_price": _cents(purchase_price),
        "purchase_date": purchase_date.isoformat() if purchase_date else None,
        "down_payment": _cents(down_payment),
        "valuation_source": valuation_source,
        "valuation_as_of": valuation_as_of.isoformat() if valuation_as_of else None,
        "include_in_net_worth": include_in_net_worth,
        "address_label": (address_label or "").strip() or None,
    }


FIELD_WIDTH = 200


def property_fields(existing: dict[str, Any]) -> dict[str, Any]:
    """The dialog's controls, prefilled from what is stored (impure only in
    that it builds controls - no page, no I/O, so it is testable).

    Every control carries an explicit width: these are Container-based and
    collapse to nothing inside a Row without one.
    """
    return {
        "kind": FormDropdown(
            label="Type",
            options=list(PROPERTY_KINDS),
            value=str(existing.get("kind") or "primary"),
            width=FIELD_WIDTH,
            variant="pulse",
        ),
        "source": FormDropdown(
            label="Value from",
            options=list(VALUATION_SOURCES),
            value=str(existing.get("valuation_source") or "user"),
            width=FIELD_WIDTH,
            variant="pulse",
        ),
        "purchase_price": FormTextField(
            label="Purchase price",
            value=_dollars(existing.get("purchase_price")),
            hint="Dollars",
            width=FIELD_WIDTH,
        ),
        "purchase_date": FormDateField(
            label="Purchased",
            value=str(existing.get("purchase_date") or ""),
            width=FIELD_WIDTH,
        ),
        "down_payment": FormTextField(
            label="Down payment",
            value=_dollars(existing.get("down_payment")),
            hint="Dollars",
            width=FIELD_WIDTH,
        ),
        "valued_on": FormDateField(
            label="Valued on",
            value=str(existing.get("valuation_as_of") or ""),
            width=FIELD_WIDTH,
        ),
    }


# Which sources a person can actually paste from today. ``kbb`` exists for
# vehicles; the valuation table's CHECK constraint is the full vocabulary.
VALUATION_INGEST_SOURCES = (
    ("zillow", "Zillow (Zestimate)"),
    ("manual", "My own figure"),
    ("kbb", "Kelley Blue Book"),
)
# Anything a site computed is an estimate; a figure a person typed is not.
_TYPED_SOURCES = frozenset({"manual"})


def valuation_payload(
    *, text: str, source: str, note: str | None = None
) -> dict[str, Any]:
    """Paste + source -> POST body (pure). Raises ValueError on an empty paste."""
    if not text.strip():
        raise ValueError("Paste a date and value per line.")
    return {
        "text": text,
        "source": source,
        "is_estimate": source not in _TYPED_SOURCES,
        "note": note,
    }


class PropertyDetailsMixin(TransactionsPanelState):
    """The Manage menu's Property details dialog."""

    def _open_property_details(self, account: dict) -> None:
        fields = property_fields(account.get("property") or {})
        kind = fields["kind"]
        source = fields["source"]
        purchase_price = fields["purchase_price"]
        purchase_date = fields["purchase_date"]
        down_payment = fields["down_payment"]
        valued_on = fields["valued_on"]

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _save() -> None:
            try:
                payload = property_payload(
                    purchase_price=purchase_price.value,
                    purchase_date=purchase_date.value,
                    down_payment=down_payment.value,
                    property_kind=str(kind.value or "primary"),
                    valuation_source=str(source.value or "user"),
                    valuation_as_of=valued_on.value,
                )
            except ValueError:
                ErrorSnackBar("Amounts must be numbers, in dollars.").launch(self.page)
                return
            dialog.open = False
            self.page.update()
            await self._save_property_details(account["id"], payload)

        dialog = StyledAlertDialog(
            title="Property details",
            body=ft.Column(
                [
                    ft.Row([kind, source], spacing=Theme.Spacing.SM),
                    ft.Row(
                        [purchase_price, purchase_date], spacing=Theme.Spacing.SM
                    ),
                    ft.Row([down_payment, valued_on], spacing=Theme.Spacing.SM),
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
            width=460,
        )
        self.page.open(dialog)

    async def _save_property_details(
        self, account_id: int, payload: dict[str, Any]
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.patch(
            f"/api/v1/finance/accounts/{account_id}/property", json=payload
        )
        if not isinstance(response, dict):
            ErrorSnackBar("Could not save those details.").launch(self.page)
            return
        SuccessSnackBar("Property details saved.").launch(self.page)
        if self._reload_accounts is not None:
            await self._reload_accounts()


def _dollars(cents: Any) -> str:
    """Stored cents -> the dollars string the field shows (blank if unset)."""
    if cents is None:
        return ""
    return f"{int(cents) / 100:.2f}"


class ValuationHistoryMixin(TransactionsPanelState):
    """The Manage menu's Valuation history dialog: paste a dated series."""

    def _open_valuation_history(self, account: dict) -> None:
        source = FormDropdown(
            label="Source",
            options=list(VALUATION_INGEST_SOURCES),
            value="zillow",
            width=FIELD_WIDTH,
            variant="pulse",
        )
        pasted = FormTextField(
            label="Paste the history",
            hint="Aug 2026    $711.2K",
            multiline=True,
            min_lines=6,
            max_lines=12,
            width=420,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _save() -> None:
            try:
                payload = valuation_payload(
                    text=pasted.value or "",
                    source=str(source.value or "manual"),
                )
            except ValueError as exc:
                ErrorSnackBar(str(exc)).launch(self.page)
                return
            dialog.open = False
            self.page.update()
            await self._ingest_valuations(account["id"], payload)

        dialog = StyledAlertDialog(
            title="Valuation history",
            body=ft.Column(
                [
                    SecondaryText(
                        "One date and value per line. A month (Aug 2026) or a "
                        "full date both work, and re-pasting a longer window "
                        "updates what overlaps."
                    ),
                    source,
                    pasted,
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
                    on_click_callable=_save, text="Import", compact=True
                ),
            ],
            width=480,
        )
        self.page.open(dialog)

    async def _ingest_valuations(
        self, account_id: int, payload: dict[str, Any]
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.post(
            f"/api/v1/finance/accounts/{account_id}/valuations/bulk", json=payload
        )
        if not isinstance(response, dict):
            # The parse error names the line it choked on; the API returns
            # it as a 400, and swallowing that would leave the user
            # guessing which of 121 rows was wrong.
            ErrorSnackBar("Could not read that series.").launch(self.page)
            return
        SuccessSnackBar(
            f"{response['added']} added, {response['updated']} updated."
        ).launch(self.page)
        if self._reload_accounts is not None:
            await self._reload_accounts()
