"""
Payment Service Card

Dashboard card for payment processing status monitoring.
"""

import flet as ft
from app.services.payment.constants import PAYMENT_COMPONENT_NAME
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_subtitle

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class PaymentCard:
    """Payment service card showing provider status and transaction summary."""

    def __init__(self, component_data: ComponentStatus) -> None:
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with transaction stats."""
        total_txns = self.metadata.get("total_transactions", 0)
        revenue_cents = self.metadata.get("total_revenue_cents", 0)
        active_subs = self.metadata.get("active_subscriptions", 0)
        revenue_display = f"${revenue_cents / 100:,.2f}" if revenue_cents else "$0.00"

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [create_metric_container("Transactions", f"{total_txns:,}")],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    ft.Row(
                        [
                            create_metric_container("Revenue", revenue_display),
                            create_metric_container("Subscriptions", str(active_subs)),
                        ],
                        expand=True,
                    ),
                ],
                spacing=0,
            ),
            expand=True,
        )

    def _create_card_content(self) -> ft.Container:
        """Create the full card content with header and metrics."""
        subtitle = get_component_subtitle(
            f"service_{PAYMENT_COMPONENT_NAME}", self.metadata
        )

        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Payment",
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
        """Build the payment card."""
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            component_name=f"service_{PAYMENT_COMPONENT_NAME}",
            component_data=self.component_data,
            border_color=border_color,
        )
