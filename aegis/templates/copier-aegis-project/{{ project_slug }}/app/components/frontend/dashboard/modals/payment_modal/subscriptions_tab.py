"""The Subscriptions tab: what is billing, and when it bills next."""

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
from .formatting import _fmt_datetime

_SUBSCRIPTION_STATUS_COLORS: dict[str, str] = {
    "active": Theme.Colors.SUCCESS,
    "trialing": Theme.Colors.INFO,
    "past_due": Theme.Colors.WARNING,
    "canceled": Theme.Colors.ERROR,
    "unpaid": Theme.Colors.ERROR,
    "incomplete": Theme.Colors.WARNING,
}


class SubscriptionsTab(ft.Container):
    """Active subscriptions with billing period."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.page = page
        metadata = component_data.metadata or {}
        subs: list[dict[str, Any]] = metadata.get("recent_subscriptions", []) or []

        columns = [
            DataTableColumn("ID", width=60),
            DataTableColumn("Customer", width=200),
            DataTableColumn("Plan", width=180),
            DataTableColumn("Status", width=140),
            DataTableColumn("Last activity", width=150),
            DataTableColumn("Provider ID"),
        ]

        rows: list[list[ft.Control]] = []
        for s in subs:
            status = s.get("status", "")
            status_color = _SUBSCRIPTION_STATUS_COLORS.get(status, Theme.Colors.INFO)
            cancel_note = ""
            if s.get("cancel_at_period_end"):
                cancel_note = " (cancels at period end)"
            # Prefer the customer's name; fall back to their email; and
            # only show an em-dash when neither is present (e.g. the sub
            # predates customer linking).
            customer_display = s.get("customer_name") or s.get("customer_email") or "—"
            rows.append(
                [
                    TableNameText(str(s.get("id", ""))),
                    TableCellText(customer_display),
                    TableNameText(f"{s.get('plan_name', '')}{cancel_note}"),
                    ft.Row(
                        [Tag(status, color=status_color)],
                        tight=True,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    TableCellText(_fmt_datetime(s.get("updated_at"))),
                    TableCellText(s.get("provider_subscription_id", "")),
                ]
            )

        body: ft.Control
        if rows:
            body = DataTable(
                columns=columns,
                rows=rows,
                row_padding=8,
                empty_message="No subscriptions",
            )
        else:
            body = EmptyStatePlaceholder(
                message="No subscriptions. Start a recurring checkout to see one here."
            )

        self.content = ft.Column(
            [body],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.expand = True
