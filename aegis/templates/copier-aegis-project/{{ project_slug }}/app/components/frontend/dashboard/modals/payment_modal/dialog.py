"""The payment modal itself: six tabs over one component status."""

import flet as ft
from app.components.frontend.controls.tabs import PulseTabs
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from ...cards.card_utils import get_status_detail
from ..base_detail_popup import BaseDetailPopup
from .actions_tab import ActionsTab
from .disputes_tab import DisputesTab
from .overview_tab import OverviewTab
from .settings_tab import SettingsTab
from .subscriptions_tab import SubscriptionsTab
from .transactions_tab import TransactionsTab


class PaymentDetailDialog(BaseDetailPopup):
    """Detail modal for the payment service."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        metadata = component_data.metadata or {}
        subtitle = metadata.get("provider_display_name", "Stripe")

        tabs = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Overview", content=OverviewTab(component_data, page)),
                ft.Tab(
                    text="Transactions",
                    content=TransactionsTab(component_data, page),
                ),
                ft.Tab(
                    text="Subscriptions",
                    content=SubscriptionsTab(component_data, page),
                ),
                ft.Tab(
                    text="Disputes",
                    content=DisputesTab(component_data, page),
                ),
                ft.Tab(
                    text="Actions",
                    content=ActionsTab(component_data, page),
                ),
                ft.Tab(
                    text="Settings",
                    content=SettingsTab(component_data, page),
                ),
            ],
            expand=True,
        )

        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_payment"),
            subtitle_text=subtitle,
            sections=[tabs],
            scrollable=False,
            width=1280,
            height=840,
            status_detail=get_status_detail(component_data),
        )
