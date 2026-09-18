"""The Disputes tab: chargebacks, and how long is left to answer them.

The evidence deadline is the column that matters, which is why a
dispute reads its date rather than its timestamp.
"""

from typing import Any

import flet as ft
from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    Tag,
)
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import EmptyStatePlaceholder
from .formatting import _fmt_amount, _fmt_date

_DISPUTE_STATUS_COLORS: dict[str, str] = {
    "warning_issued": Theme.Colors.WARNING,
    "warning_closed": Theme.Colors.SUCCESS,
    "needs_response": Theme.Colors.ERROR,
    "under_review": Theme.Colors.INFO,
    "won": Theme.Colors.SUCCESS,
    "lost": Theme.Colors.ERROR,
    "charge_refunded": Theme.Colors.INFO,
}


class DisputesTab(ft.Container):
    """Chargebacks and early fraud warnings with evidence deadlines."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}
        disputes: list[dict[str, Any]] = metadata.get("recent_disputes", []) or []
        open_count = metadata.get("open_disputes", 0)

        columns = [
            DataTableColumn("ID", width=60),
            DataTableColumn("Txn", width=60),
            DataTableColumn("Status", width=160),
            DataTableColumn("Reason", width=160),
            DataTableColumn("Amount", width=110, alignment="right"),
            DataTableColumn("Evidence Due", width=130),
            DataTableColumn("Provider ID"),
        ]

        rows: list[list[ft.Control]] = []
        for d in disputes:
            status = d.get("status", "")
            status_color = _DISPUTE_STATUS_COLORS.get(status, Theme.Colors.INFO)
            rows.append(
                [
                    TableNameText(str(d.get("id", ""))),
                    TableCellText(str(d.get("transaction_id", ""))),
                    ft.Row(
                        [Tag(status, color=status_color)],
                        tight=True,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    TableCellText(d.get("reason") or "—"),
                    TableCellText(
                        _fmt_amount(d.get("amount", 0), d.get("currency", "usd"))
                    ),
                    TableCellText(_fmt_date(d.get("evidence_due_by"))),
                    TableCellText(d.get("provider_dispute_id", "")),
                ]
            )

        body: ft.Control
        if rows:
            body = DataTable(
                columns=columns,
                rows=rows,
                row_padding=8,
                empty_message="No disputes",
            )
        else:
            body = EmptyStatePlaceholder(
                message=(
                    "No disputes. Trigger one with "
                    "`stripe trigger charge.dispute.created`."
                )
            )

        header_text = (
            f"{open_count} open " if open_count else "No open "
        ) + "dispute(s). Respond to chargebacks via the Stripe dashboard."
        header_color = Theme.Colors.ERROR if open_count else Theme.Colors.SUCCESS

        self.content = ft.Column(
            [
                ft.Text(
                    header_text,
                    size=Theme.Typography.BODY,
                    color=header_color,
                    weight=ft.FontWeight.W_500,
                ),
                ft.Container(height=Theme.Spacing.SM),
                body,
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
