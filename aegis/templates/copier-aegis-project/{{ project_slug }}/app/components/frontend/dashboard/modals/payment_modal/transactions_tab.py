"""The Transactions tab, and what may be refunded from it.

A row gets a refund button only when its status and type both allow
one; the two sets at the top are that rule, and the action cell asks
them rather than re-deriving it. The refund dialog is here because it
is the only thing that opens it.
"""

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    DataTable,
    DataTableColumn,
    H3Text,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.buttons import (
    BaseIconButton,
    PulseButton,
)
from app.components.frontend.controls.form_fields import FormDropdown, FormTextField
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings
from app.services.payment.constants import RefundReason
from app.services.system.models import ComponentStatus

from ..modal_sections import EmptyStatePlaceholder
from .formatting import _fmt_amount, _fmt_datetime

# Transaction statuses that are refundable via POST /api/v1/payment/refund/{id}.
_REFUNDABLE_STATUSES = {"succeeded", "partially_refunded"}


_REFUNDABLE_TYPES = {"charge", "subscription"}


_TRANSACTION_STATUS_COLORS: dict[str, str] = {
    "succeeded": Theme.Colors.SUCCESS,
    "pending": Theme.Colors.WARNING,
    "failed": Theme.Colors.ERROR,
    "refunded": Theme.Colors.INFO,
    "partially_refunded": Theme.Colors.INFO,
    "canceled": Theme.Colors.ERROR,
}


class TransactionsTab(ft.Container):
    """Recent transactions with status tags."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}
        txns: list[dict[str, Any]] = metadata.get("recent_transactions", []) or []

        columns = [
            DataTableColumn("ID", width=60),
            DataTableColumn("Type", width=110),
            DataTableColumn("Status", width=140),
            DataTableColumn("Amount", width=110, alignment="right"),
            DataTableColumn("Provider ID"),
            DataTableColumn("Created", width=140),
            DataTableColumn("", width=48),  # actions
        ]

        rows: list[list[ft.Control]] = []
        for t in txns:
            status = t.get("status", "")
            status_color = _TRANSACTION_STATUS_COLORS.get(status, Theme.Colors.INFO)
            action_cell = self._build_action_cell(t)
            rows.append(
                [
                    TableNameText(str(t.get("id", ""))),
                    TableCellText(t.get("type", "")),
                    ft.Row(
                        [Tag(status, color=status_color)],
                        tight=True,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    TableCellText(
                        _fmt_amount(t.get("amount", 0), t.get("currency", "usd"))
                    ),
                    TableCellText(t.get("provider_transaction_id", "")),
                    TableCellText(_fmt_datetime(t.get("created_at"))),
                    action_cell,
                ]
            )

        body: ft.Control
        if rows:
            body = DataTable(
                columns=columns,
                rows=rows,
                row_padding=8,
                empty_message="No transactions yet",
            )
        else:
            body = EmptyStatePlaceholder(
                message="No transactions yet. Run a test checkout to see activity here."
            )

        self.content = ft.Column(
            [
                SecondaryText(
                    f"10 most recent transactions. Use `{settings.PROJECT_NAME} "
                    "payment transactions` or the REST API for full history."
                ),
                ft.Container(height=Theme.Spacing.SM),
                body,
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True

    def _build_action_cell(self, txn: dict[str, Any]) -> ft.Control:
        """Row-level action menu. Refund button for refundable charges."""
        refundable = (
            txn.get("type") in _REFUNDABLE_TYPES
            and txn.get("status") in _REFUNDABLE_STATUSES
        )
        if not refundable:
            return ft.Container(width=24)

        captured = txn

        async def handle_refund_click() -> None:
            self._open_refund_dialog(captured)

        return BaseIconButton(
            on_click_callable=handle_refund_click,
            icon=ft.Icons.CURRENCY_EXCHANGE,
            tooltip="Refund",
        )

    def _open_refund_dialog(self, txn: dict[str, Any]) -> None:
        """Open a dialog to issue a refund for a transaction."""
        page = self.page
        if not page:
            return

        txn_id = txn["id"]
        original_amount_cents: int = txn.get("amount", 0)
        currency: str = (txn.get("currency") or "usd").upper()
        original_amount_display = f"{original_amount_cents / 100:,.2f}"

        amount_field = FormTextField(
            label=f"Amount ({currency})",
            value=original_amount_display,
            hint=(
                f"Leave at {original_amount_display} for full refund, "
                "or lower for partial"
            ),
            width=280,
        )
        reason_field = FormDropdown(
            label="Reason",
            options=[(value, RefundReason.LABELS[value]) for value in RefundReason.ALL],
            value=RefundReason.DEFAULT,
            width=360,
        )
        dialog_holder: dict[str, ft.AlertDialog] = {}

        async def close_dialog() -> None:
            page.close(dialog_holder["dialog"])

        async def do_refund() -> None:
            await close_dialog()

            amount_cents: int | None = None
            raw_amount = amount_field.value.strip()
            if raw_amount:
                try:
                    parsed = float(raw_amount)
                    amount_cents = int(round(parsed * 100))
                    if amount_cents >= original_amount_cents:
                        amount_cents = None  # treat as full refund
                except ValueError:
                    page.open(
                        ft.SnackBar(
                            content=ft.Text("Invalid amount"),
                            bgcolor=Theme.Colors.ERROR,
                        )
                    )
                    return

            payload: dict[str, Any] = {
                "reason": reason_field.value or RefundReason.DEFAULT,
            }
            if amount_cents is not None:
                payload["amount"] = amount_cents

            from app.components.frontend.controls.snack_bar import (
                ErrorSnackBar,
                SuccessSnackBar,
            )
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(page).api_client
            status, body = await api.request_with_status(
                "POST",
                f"/api/v1/payment/refund/{txn_id}",
                json=payload,
            )

            if status == 200:
                # Invalidate so the next dashboard refresh shows updated status.
                try:
                    from app.services.payment.health import (
                        invalidate_payment_health_cache,
                    )

                    invalidate_payment_health_cache()
                except Exception:
                    pass

                SuccessSnackBar(
                    f"Refund issued for transaction #{txn_id}. "
                    "Dashboard will update on next refresh."
                ).launch(page)
            elif status == 404:
                ErrorSnackBar("Transaction not found.").launch(page)
            else:
                detail = (
                    body.get("detail")
                    if isinstance(body, dict) and body.get("detail")
                    else f"status {status}"
                )
                ErrorSnackBar(f"Refund failed: {detail}").launch(page)

        dialog = ft.AlertDialog(
            modal=True,
            title=H3Text(f"Refund transaction #{txn_id}"),
            content=ft.Column(
                [
                    BodyText(f"Original amount: {original_amount_display} {currency}"),
                    ft.Container(height=Theme.Spacing.MD),
                    amount_field,
                    ft.Container(height=Theme.Spacing.SM),
                    reason_field,
                ],
                tight=True,
                width=420,
            ),
            actions=[
                PulseButton(
                    on_click_callable=close_dialog,
                    text="Cancel",
                    variant="muted",
                ),
                PulseButton(
                    on_click_callable=do_refund,
                    text="Issue Refund",
                    variant="amber",
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        )
        dialog_holder["dialog"] = dialog
        page.open(dialog)
