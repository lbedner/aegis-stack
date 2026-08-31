"""The split editor: carve one transaction into category lines.

One mixin of ``TransactionsPanel`` - state contract in ``base``. The
dialog collects positive dollar amounts (what the user actually knows)
and shows live where the unclaimed difference will land: the backend
fills it as a remainder line under the parent's own category, so the
lines always add up to the parent and the parent itself never changes.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.pickers import picker_trigger_cell
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.controls.table import TableCellText
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _TXN_CATEGORY_COLUMN_WIDTH,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _parse_dollars,
    _usd,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
    split_summary_label,
    split_tooltip,
)
from app.components.frontend.theme import AegisTheme as Theme


class SplitsFlowMixin(TransactionsPanelState):
    """Split a register row into category lines, or take a split off."""

    def _split_category_cell(self, record: dict) -> ft.Control:
        """The register's category cell for a split parent: the lines as
        summary and tooltip, and the split editor (not the category
        picker) on tap - a split parent's own category no longer
        reports, so re-picking it would be a lie."""
        splits = record.get("splits") or []
        return picker_trigger_cell(
            TableCellText(split_summary_label(splits)),
            _TXN_CATEGORY_COLUMN_WIDTH,
            on_tap=lambda _e, r=record: self._open_split_dialog(r),
            tooltip=f"{split_tooltip(splits)}\nClick to edit the split",
        )

    def _txn_expand_content(self, record: dict) -> ft.Control:
        """A register row's expand content with every row action wired:
        tag removal plus the split section's edit/remove/way-in."""
        return _transaction_expanded_content(
            record,
            on_remove_tag=self._remove_tag,
            on_edit_split=self._open_split_dialog,
            on_unsplit=self._remove_split,
        )

    def _open_split_dialog(self, txn: dict) -> None:
        total = abs(int(txn.get("amount") or 0))
        parent_category = txn.get("category") or "Uncategorized"
        lines: list[dict[str, Any]] = []
        line_rows = ft.Column([], spacing=Theme.Spacing.SM, tight=True)
        remainder_line = SecondaryText("", size=Theme.Typography.BODY_SMALL)

        def _claimed() -> int:
            return sum(_parse_dollars(line["amount"].value) for line in lines)

        def _refresh_remainder(_e: ft.ControlEvent | None = None) -> None:
            remainder = total - _claimed()
            if remainder > 0:
                remainder_line.value = (
                    f"{_usd(remainder)} unassigned - stays as {parent_category}"
                )
                remainder_line.color = Theme.Colors.TEXT_SECONDARY
            elif remainder == 0:
                remainder_line.value = "Fully allocated."
                remainder_line.color = Theme.Colors.TEXT_SECONDARY
            else:
                remainder_line.value = (
                    f"Over by {_usd(-remainder)} - lines exceed the transaction."
                )
                remainder_line.color = Theme.Colors.ERROR
            if remainder_line.page is not None:
                remainder_line.update()

        def _add_line(
            _e: ft.ControlEvent | None = None,
            *,
            amount: str = "",
            category_id: int | None = None,
            memo: str = "",
        ) -> None:
            line: dict[str, Any] = {
                "amount": FormTextField(
                    label="Amount ($)",
                    value=amount,
                    width=110,
                    on_change=_refresh_remainder,
                ),
                "category": FormDropdown(
                    label="Category",
                    options=self._categories,
                    value=str(category_id) if category_id is not None else None,
                    width=230,
                    max_menu_height=320,
                ),
                "memo": FormTextField(label="Memo", value=memo, width=150),
            }

            def _drop(_ev: ft.ControlEvent, target: dict[str, Any] = line) -> None:
                lines.remove(target)
                line_rows.controls.remove(target["row"])
                _refresh_remainder()
                if line_rows.page is not None:
                    line_rows.update()

            line["row"] = ft.Row(
                [
                    line["amount"],
                    line["category"],
                    line["memo"],
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_size=16,
                        icon_color=Theme.Colors.TEXT_SECONDARY,
                        tooltip="Remove this line",
                        on_click=_drop,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.END,
            )
            lines.append(line)
            line_rows.controls.append(line["row"])
            if line_rows.page is not None:
                line_rows.update()
                _refresh_remainder()

        for split in txn.get("splits") or []:
            _add_line(
                amount=f"{abs(int(split.get('amount') or 0)) / 100:.2f}",
                category_id=split.get("category_id"),
                memo=split.get("memo") or "",
            )
        if not lines:
            _add_line()
        _refresh_remainder()

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _save() -> None:
            parts = []
            for line in lines:
                cents = _parse_dollars(line["amount"].value)
                if cents <= 0:
                    continue
                category_value = line["category"].value
                parts.append(
                    {
                        "amount": cents,
                        "category_id": int(category_value)
                        if category_value
                        else None,
                        "memo": line["memo"].value.strip() or None,
                    }
                )
            if not parts:
                ErrorSnackBar("Enter at least one line amount.").launch(self.page)
                return
            if _claimed() > total:
                ErrorSnackBar("The lines exceed the transaction amount.").launch(
                    self.page
                )
                return
            dialog.open = False
            self.page.update()
            await self._save_split(txn, parts)

        header = SecondaryText(
            f"{txn.get('merchant') or txn.get('name') or 'Transaction'}"
            f" · {_usd(txn.get('amount', 0))}",
            size=Theme.Typography.BODY_SMALL,
        )
        dialog = StyledAlertDialog(
            title="Split transaction",
            body=ft.Column(
                [
                    header,
                    line_rows,
                    PulseButton(
                        on_click_callable=lambda: _async_noop(_add_line),
                        text="Add line",
                        variant="muted",
                        compact=True,
                    ),
                    remainder_line,
                ],
                spacing=Theme.Spacing.MD,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
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
                    text="Save split",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=620,
        )
        self.page.open(dialog)

    async def _save_split(self, txn: dict, parts: list[dict[str, Any]]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            f"/api/v1/finance/transactions/{txn['id']}/split", json={"parts": parts}
        )
        if not isinstance(result, dict) or "items" not in result:
            detail = (
                result.get("detail") if isinstance(result, dict) else None
            ) or "Could not split that transaction."
            ErrorSnackBar(str(detail)).launch(self.page)
            return
        SuccessSnackBar(
            f"Split into {len(result['items'])} lines."
        ).launch(self.page)
        await self._load()

    def _remove_split(self, txn: dict) -> None:
        """Row-expand's "Remove split" - back to one line, one category."""
        if self.page is None:
            return
        self.page.run_task(self._remove_split_async, txn)

    async def _remove_split_async(self, txn: dict) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.delete(f"/api/v1/finance/transactions/{txn['id']}/split")
        if not isinstance(result, dict) or "removed" not in result:
            ErrorSnackBar("Could not remove that split.").launch(self.page)
            return
        SuccessSnackBar("Split removed.").launch(self.page)
        await self._load()


async def _async_noop(callback: Any) -> None:
    """Bridge a sync handler into ``PulseButton``'s async-only contract."""
    callback()
