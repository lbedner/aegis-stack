"""
Finance Service Card

Dashboard card for the finance aggregator: a net-worth headline plus account
and connection counts, with the service's health colour. Mirrors
``payment_card.py``; reads everything from ``component_data.metadata`` (the
``check_finance_service_health`` summary) — no DB access from the frontend.
"""

import flet as ft

from app.services.finance.constants import FINANCE_COMPONENT_NAME
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


def _usd(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.2f}"


class FinanceCard:
    """Finance service card: net worth + account / connection summary."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        """Net-worth headline, then account / connection counts."""
        net_worth = self.metadata.get("net_worth_amount", 0)
        accounts = self.metadata.get("account_count", 0)
        connections = self.metadata.get("connection_count", 0)
        insights = self.metadata.get("new_insight_count", 0)

        counts = [
            create_metric_container("Accounts", f"{accounts:,}"),
            create_metric_container("Connections", f"{connections:,}"),
        ]
        # Surface the "wasting money" nudge only when there's something to see.
        if insights:
            counts.append(create_metric_container("Insights", f"{insights:,}"))

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [create_metric_container("Net Worth", _usd(net_worth))],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    ft.Row(counts, expand=True),
                ],
                spacing=0,
            ),
            expand=True,
        )

    def _create_card_content(self) -> ft.Container:
        subtitle = get_component_subtitle(
            f"service_{FINANCE_COMPONENT_NAME}", self.metadata
        )

        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Finance",
                        subtitle,
                        self.component_data,
                    ),
                    self._create_metrics_section(),
                ],
                spacing=0,
            ),
            padding=ft.padding.all(16),
            expand=True,
        )

    def build(self) -> ft.Container:
        """Build the finance card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            component_name=FINANCE_COMPONENT_NAME,
            component_data=self.component_data,
            border_color=border_color,
        )
