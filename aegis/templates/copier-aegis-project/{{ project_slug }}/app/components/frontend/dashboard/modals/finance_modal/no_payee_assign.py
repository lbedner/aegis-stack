"""Assigning a payee to a group of unnamed transactions."""

from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    NativeDropdown,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormTextField,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar

# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
# One height for every Overview card, so the row has a single baseline.
# Named slices in the spending donut (and rows in the list under it) before
# the tail folds into "Other". Five left "Other" as the biggest slice on any
# real ledger, which hides exactly the breakdown the card exists to show.
# Measured against a real ledger (23 parent-level categories after the
# spending_by_category rollup): 10 slices still left "Other" at 16.3%; 15
# gets it to 5.3%, with everything past #15 individually under 1% of total
# spend - the tail at that point really is "everything else", not a few
# disguised top categories. PieChartCard's legend scrolls within its fixed
# height (modal_sections.py) rather than clipping, so this isn't bounded
# by legend space anymore.
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _DENSE_ROW_HEIGHT,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    _group_columns,
    _group_rows,
    _group_table_height,
)
from app.components.frontend.theme import AegisTheme as Theme


class PayeeAssignMixin:
    """Giving a bank-descriptor group a payee.

    Three ways in - the group dialog, picking an existing merchant, and
    creating one - all ending in the same PATCH. The host is
    ``NoPayeePanel``; what it provides is declared here so this module
    type checks on its own.
    """

    if TYPE_CHECKING:
        page: ft.Page | None
        _merchants: list[dict[str, Any]]
        _selected_keys: set[str]

        async def _load(self, *args: Any, **kwargs: Any) -> Any: ...
        def _set_busy(self, busy: bool) -> None: ...
        def _update_selection_label(self) -> None: ...

    def _open_group_dialog(self, groups: list[dict]) -> None:
        """Name one group, or every checked group at once. A dialog rather
        than the anchored picker: this settles up to a thousand
        transactions at once, so it deserves a deliberate confirm - and
        DataTable's row click carries no tap coordinates for the popup to
        anchor to anyway.

        The name is pre-filled from the key but fully editable, because the
        key is a descriptor, not a brand: "MCDONALD S" wants fixing to
        "McDonald's", and "NON CHASE ATM WITHDRAW" is not a merchant at all
        (Cancel is the right answer there).

        For a MULTI-group sweep the prefill is dropped: the whole point is
        that the descriptors disagree ("DOORDASH*CROWN FRIEDSAN..." vs
        "BT*DD *DOORDASH MCDOSAN..."), so any one of their suggested names
        would be an arbitrary pick presented as a default. The samples are
        listed instead, and you type the brand once.
        """
        if not groups:
            return
        count = sum(g.get("count", 0) for g in groups)
        name_field = FormTextField(
            label="Payee name",
            value=groups[0].get("suggested_name", "") if len(groups) == 1 else "",
            width=300,
        )
        # Optional, and only worth filling when the guess would miss. The
        # icon lookup otherwise tries "<name>.com", which cannot reach a
        # different TLD ("aegis-stack.io"), cannot keep punctuation that
        # was part of the name ("Aegis Stack" -> "aegisstack"), and can
        # land confidently on somebody else's site.
        website_field = FormTextField(
            label="Website (optional)",
            hint="aegis-stack.io - only needed if the logo looks wrong",
            width=300,
        )
        # Attaching to an EXISTING payee is the other half: these
        # descriptors often belong to a payee you already created.
        existing = NativeDropdown(
            options=[ft.dropdown.Option(key=k, text=t) for k, t in self._merchants],
            hint_text="…or attach to an existing payee",
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        from app.components.frontend.state.session_state import get_session_state

        async def _confirm() -> None:
            payload: dict[str, object] = {
                "keys": [g.get("key", "") for g in groups if g.get("key")]
            }
            if existing.value:
                payload["merchant_id"] = int(existing.value)
            else:
                typed = (name_field.value or "").strip()
                if not typed:
                    ErrorSnackBar("Give the payee a name.").launch(self.page)
                    return
                payload["name"] = typed
            site = (website_field.value or "").strip()
            if site:
                payload["website_url"] = site
            dialog.open = False
            self.page.update()
            self._set_busy(True)
            try:
                result = await get_session_state(self.page).api_client.post(
                    "/api/v1/finance/payee-groups/assign", json=payload
                )
                if not isinstance(result, dict):
                    ErrorSnackBar(
                        "Could not name that group."
                        if len(groups) == 1
                        else "Could not name those groups."
                    ).launch(self.page)
                    return
                SuccessSnackBar(
                    f"Payee set on {result.get('updated', 0):,} transactions."
                ).launch(self.page)
                # These keys are settled - they no longer exist in the
                # backlog, so carrying the ticks over would re-apply to
                # whatever slid into those row positions.
                self._selected_keys.clear()
                self._update_selection_label()
                await self._load()
            finally:
                # finally: an API error must not leave the bar spinning
                # forever with no way back.
                self._set_busy(False)

        # The full table, not a sample of it: this is the confirm step for
        # a write that can settle thousands of transactions, so every row
        # it touches has to be visible and checkable - with its count and
        # its total, the two numbers that say whether a descriptor really
        # belongs to this payee. Same columns as the tab behind it.
        preview = DataTable(
            columns=_group_columns(),
            rows=_group_rows(groups),
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=_group_table_height(
                len(groups), getattr(self.page, "height", None)
            ),
        )
        lead = (
            f"{count:,} transaction{'s' if count != 1 else ''} look like this one:"
            if len(groups) == 1
            else (
                f"{len(groups):,} groups, {count:,} transactions. "
                "They all get this payee:"
            )
        )
        dialog = StyledAlertDialog(
            title="Name this payee" if len(groups) == 1 else "Name these payees",
            body=ft.Column(
                [
                    SecondaryText(lead),
                    preview,
                    ft.Container(height=Theme.Spacing.SM),
                    # One row, not a stack. Three 300px fields in a 980px
                    # dialog left two thirds of the width empty while
                    # costing ~140px of height - height being the scarce
                    # dimension here, since the panel clips (HARD_EDGE)
                    # rather than shrinks when it outgrows the window, and
                    # what gets clipped is the action row at the bottom.
                    ft.Row(
                        [name_field, website_field, existing],
                        spacing=Theme.Spacing.MD,
                        vertical_alignment=ft.CrossAxisAlignment.END,
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
                    on_click_callable=_confirm,
                    text=f"Name {count:,}",
                    variant="teal",
                    compact=True,
                ),
            ],
            # Wide enough for the descriptors to read whole. They run to
            # ~100 characters ("DOORDASH DASHPASS SAN FRANCISCO MARISA
            # BEDNER-14013-NT_MKD9OUT0 +16506819470"), and the tail is
            # often the only thing distinguishing two rows - ellipsizing
            # it defeats the point of showing the table.
            width=980,
        )
        self.page.open(dialog)

    def _pick_merchant(self, transaction_ids: list[int], merchant_key: str) -> None:
        if merchant_key and transaction_ids and self.page:
            self.page.run_task(self._apply, transaction_ids, int(merchant_key))

    def _create_merchant(self, transaction_ids: list[int], name: str) -> None:
        if name and transaction_ids and self.page:
            self.page.run_task(self._create_and_apply, transaction_ids, name)

    async def _create_and_apply(self, transaction_ids: list[int], name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await api.post("/api/v1/finance/merchants", json={"name": name})
        if not isinstance(created, dict) or created.get("id") is None:
            ErrorSnackBar(f'Could not create the payee "{name}".').launch(self.page)
            return
        await self._apply(transaction_ids, int(created["id"]))

    async def _apply(self, transaction_ids: list[int], merchant_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            result = await api.post(
                "/api/v1/finance/transactions/assign-merchant",
                json={"transaction_ids": transaction_ids, "merchant_id": merchant_id},
            )
            if not isinstance(result, dict):
                ErrorSnackBar("Could not set the payee.").launch(self.page)
                return
            updated = result.get("updated", 0)
            SuccessSnackBar(
                f"Payee set on {updated} transaction{'s' if updated != 1 else ''}."
            ).launch(self.page)
            await self._load()
        finally:
            self._set_busy(False)
