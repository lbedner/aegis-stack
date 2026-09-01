"""
Communications Service Card

Modern card component specifically designed for communications service monitoring.
Shows email (Resend), SMS (Twilio), and voice call status with a clean layout.
"""

import flet as ft
from app.services.system.models import ComponentStatus

from .card_container import CardContainer
from .card_utils import (
    create_header_row,
    create_metric_container,
    get_status_colors,
)


class CommsCard:
    """
    A clean communications service card with real metrics.

    Features:
    - Real provider configuration from health checks
    - Title and health status header
    - Highlighted metric containers
    - Responsive design
    """

    def __init__(self, component_data: ComponentStatus):
        """Initialize with communications service data from health check."""
        self.component_data = component_data
        self.metadata = component_data.metadata or {}

    def _create_metrics_section(self) -> ft.Container:
        """Create the metrics section with a clean grid layout."""
        # Get real data from metadata
        email_configured = self.metadata.get("email_configured", False)
        sms_configured = self.metadata.get("sms_configured", False)
        voice_configured = self.metadata.get("voice_configured", False)

        # Get provider info
        email_provider = self.metadata.get("email_provider", "None")
        sms_provider = self.metadata.get("sms_provider", "None")

        # Format display values
        email_display = email_provider.title() if email_configured else "None"
        sms_display = sms_provider.title() if sms_configured else "None"
        voice_display = "Twilio" if voice_configured else "None"

        return ft.Container(
            content=ft.Column(
                [
                    # Row 1: Email (full width)
                    ft.Row(
                        [create_metric_container("Email", email_display)],
                        expand=True,
                    ),
                    ft.Container(height=12),
                    # Row 2: SMS and Voice
                    ft.Row(
                        [
                            create_metric_container("SMS", sms_display),
                            create_metric_container("Voice", voice_display),
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
        return ft.Container(
            content=ft.Column(
                [
                    create_header_row(
                        "Comms Service",
                        "Resend + Twilio",
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
        """Build and return the complete communications card."""
        # Get colors based on component status
        _, _, border_color = get_status_colors(self.component_data)

        return CardContainer(
            content=self._create_card_content(),
            border_color=border_color,
            component_data=self.component_data,
            component_name="service_comms",
        )
