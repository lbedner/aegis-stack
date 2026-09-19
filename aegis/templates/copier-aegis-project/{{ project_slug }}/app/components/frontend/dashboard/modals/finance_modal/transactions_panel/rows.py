"""Building one register row, cell by cell.

Out of ``panel.py``'s ``_load``, which was 299 lines with five cell
closures buried in the middle of it. They are a class here because the
constructor is the honest list of what a row needs to render - two
pickers, the account-name map, a tag-tap handler, and whether the
register is showing every account - and that list was previously
discoverable only by reading the closure bodies.

The rule worth having a seam for: DataTable sorts a control cell by its
``.data`` (see ``data_table.py``'s ``cell_text``). Payee and Tags both
render a ``Row``, which has no ``.value``, so both columns stop sorting
the moment someone builds one without setting ``.data`` - silently, and
only noticed by a user clicking the header. ``test_register_rows.py``
pins it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import flet as ft

from app.components.frontend.controls.pickers import picker_trigger_cell
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.table import (
    TableCellText,
    TableNameText,
)
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _TXN_CATEGORY_COLUMN_WIDTH,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
    _trade_type_label,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    transaction_tag_chips,
)
from app.components.frontend.dashboard.modals.modal_sections import date_cell
from app.components.frontend.theme import AegisTheme as Theme


class _Picker(Protocol):
    """The slice of a picker button a cell actually uses."""

    def open_for(self, ids: list[Any], event: ft.ControlEvent) -> Any: ...


class RegisterRowBuilder:
    """One register row per call, for transactions and trades alike."""

    def __init__(
        self,
        *,
        all_accounts: bool,
        account_names: dict[Any, str],
        category_picker: _Picker,
        merchant_picker: _Picker,
        on_tag_tap: Callable[[dict], None],
        split_category_cell: Callable[[dict], ft.Control],
    ) -> None:
        """
        Args:
            all_accounts: Register is showing every account, so rows
                carry an Account column.
            account_names: Account id -> display name, for that column.
            category_picker: Opened by tapping a category cell.
            merchant_picker: Opened by tapping a payee cell.
            on_tag_tap: Filters the register to the tapped tag.
            split_category_cell: Renders the category cell for a split
                transaction, which the panel owns because a split has
                its own editing flow.
        """
        self._all_accounts = all_accounts
        self._account_names = account_names
        self._category_picker = category_picker
        self._merchant_picker = merchant_picker
        self._filter_by_tag = on_tag_tap
        self._split_category_cell = split_category_cell

    def category_cell(self, record: dict) -> ft.Control:
        # Re-categorizing an ALREADY-categorized transaction - unlike
        # UncategorizedPanel's placeholder, this shows the current
        # pick as the trigger's own label, same idea as any other
        # "click a value to change it" field.
        txn_id = record.get("id")
        if record.get("is_split") and record.get("splits"):
            return self._split_category_cell(record)
        label = TableCellText(record.get("category") or "Uncategorized")
        if txn_id is None:
            return label
        return picker_trigger_cell(
            label,
            _TXN_CATEGORY_COLUMN_WIDTH,
            on_tap=lambda e, t=txn_id: self._category_picker.open_for([t], e),
            tooltip="Click to change category",
        )

    def payee_cell(self, record: dict) -> ft.Control:
        # Shows the assigned PAYEE when there is one, falling back to
        # the raw bank descriptor - Quicken's behavior, and the reason
        # the descriptor isn't lost either way is that the row's
        # inline-expand detail still lists "Original description".
        # Assigning here is what makes a bill survive the descriptor
        # changing later (domains/domains/detection/recurring/cadence.py's _payee_key).
        txn_id = record.get("id")
        payee = record.get("merchant")
        raw = record.get("name") or ""
        if txn_id is None:
            return TableNameText(raw)
        cell = picker_trigger_cell(
            ft.Row(
                [
                    ProviderIcon(payee or raw, record.get("icon_b64")),
                    ft.Container(content=TableNameText(payee or raw), expand=True),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            None,
            on_tap=lambda e, t=txn_id: self._merchant_picker.open_for([t], e),
            tooltip=(
                f"Payee: {payee}\n{raw}\nClick to change"
                if payee
                else "No payee assigned - click to set one"
            ),
        )
        # DataTable sorts a control cell by its .data (see
        # data_table.py's cell_text) - a Row has no .value of its
        # own, so Payee would silently stop sorting without this.
        cell.data = payee or raw
        return cell

    def account_cells(self, record: dict) -> list[ft.Control]:
        if not self._all_accounts:
            return []
        return [
            TableCellText(
                self._account_names.get(record.get("account_id"), "\u2014")
            )
        ]

    def tags_cell(self, record: dict) -> ft.Control:
        tags = record.get("tags") or []
        if not tags:
            cell = ft.Container(content=TableCellText(""))
            cell.data = ""
            return cell
        cell = ft.Row(
            transaction_tag_chips(
                tags, on_tap=self._filter_by_tag, cap=2, compact=True
            ),
            spacing=Theme.Spacing.XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        # A Row has no .value, so the Tags column would silently stop
        # sorting without this (same note as the payee cell).
        cell.data = ", ".join(t.get("name", "") for t in tags)
        return cell

    def row(self, kind: str, record: dict) -> list[ft.Control]:
        if kind == "trade":
            return [
                date_cell(record.get("trade_date")),
                *self.account_cells(record),
                TableNameText(
                    record.get("name") or _trade_type_label(record.get("type"))
                ),
                # Trades are not categorized - they are position moves,
                # not spending.
                TableCellText("\u2014"),
                self.tags_cell(record),
                TableCellText(_trade_type_label(record.get("type")).lower()),
                _amount_cell(record.get("amount", 0)),
            ]
        return [
            date_cell(record.get("date")),
            *self.account_cells(record),
            self.payee_cell(record),
            self.category_cell(record),
            self.tags_cell(record),
            TableCellText(record.get("source", "")),
            _amount_cell(
                record.get("amount", 0),
                excluded=bool(record.get("excluded_from_reports")),
            ),
        ]
