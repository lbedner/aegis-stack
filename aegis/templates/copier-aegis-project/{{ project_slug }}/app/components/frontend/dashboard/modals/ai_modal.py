"""
AI Service Detail Modal

Displays comprehensive AI service information including provider configuration,
conversation statistics, usage metrics, and analytics.
"""

import flet as ft

from app.components.frontend.controls import SecondaryText, Tag
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.discovery import optional
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title

from ..cards.card_utils import PROVIDER_COLORS, get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard

# The optional tabs, where the stack ships them (``optional``: a missing
# module is "not here"; one that fails to import still raises). Analytics,
# the Cloud Catalog, Memory and Agents need the database backend; RAG and
# Voice their service options.
_MODALS = "app.components.frontend.dashboard.modals"
AIAnalyticsTab = optional(f"{_MODALS}.ai_analytics_tab", "AIAnalyticsTab")
RAGTab = optional(f"{_MODALS}.rag_tab", "RAGTab")
LLMCatalogTab = optional(f"{_MODALS}.llm_catalog_tab", "LLMCatalogTab")
MemoryModulesTab = optional(f"{_MODALS}.memory_modules_tab", "MemoryModulesTab")
AgentsTab = optional(f"{_MODALS}.agents_tab", "AgentsTab")
VoiceSettingsTab = optional(f"{_MODALS}.voice_settings", "VoiceSettingsTab")


class OverviewSection(ft.Container):
    """Overview section showing key AI service metrics."""

    def __init__(self, metadata: dict) -> None:
        """
        Initialize overview section.

        Args:
            metadata: Component metadata containing conversation stats
        """
        super().__init__()

        total_conversations = metadata.get("total_conversations", 0)
        total_messages = metadata.get("total_messages", 0)
        unique_users = metadata.get("unique_users", 0)

        self.content = ft.Row(
            [
                MetricCard(
                    "Total Conversations",
                    str(total_conversations),
                    Theme.Colors.PRIMARY,
                ),
                MetricCard("Total Messages", str(total_messages), Theme.Colors.INFO),
                MetricCard("Unique Users", str(unique_users), Theme.Colors.SUCCESS),
            ],
            spacing=Theme.Spacing.MD,
        )
        self.padding = Theme.Spacing.MD


class ServiceInfoSection(ft.Container):
    """Compact service info section with inline layout."""

    def __init__(self, metadata: dict) -> None:
        """
        Initialize service info section.

        Args:
            metadata: Component metadata containing provider config
        """
        super().__init__()

        provider = metadata.get("provider", "Unknown")
        model = metadata.get("model", "Unknown")
        streaming = metadata.get("provider_supports_streaming", False)
        free_tier = metadata.get("provider_free_tier", False)

        # Display name mapping for providers
        provider_display_names = {
            "public": "LLM7.io",
        }
        provider_display = provider_display_names.get(
            provider.lower(), provider.upper()
        )

        provider_color = PROVIDER_COLORS.get(
            provider.lower(), ft.Colors.ON_SURFACE_VARIANT
        )

        # Provider row
        provider_tags = [Tag(text=provider_display, color=provider_color)]
        if free_tier:
            provider_tags.append(Tag(text="FREE TIER", color=Theme.Colors.SUCCESS))

        provider_row = ft.Row(
            [
                SecondaryText(
                    "Provider", weight=Theme.Typography.WEIGHT_SEMIBOLD, width=80
                ),
                ft.Row(provider_tags, spacing=4),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Model row
        model_row = ft.Row(
            [
                SecondaryText(
                    "Model", weight=Theme.Typography.WEIGHT_SEMIBOLD, width=80
                ),
                Tag(text=model, color=Theme.Colors.INFO),
            ],
            spacing=Theme.Spacing.SM,
        )

        # Streaming row
        streaming_row = ft.Row(
            [
                SecondaryText(
                    "Streaming", weight=Theme.Typography.WEIGHT_SEMIBOLD, width=80
                ),
                SecondaryText("Enabled" if streaming else "Disabled"),
            ],
            spacing=Theme.Spacing.SM,
        )

        self.content = ft.Column(
            [provider_row, model_row, streaming_row],
            spacing=Theme.Spacing.XS,
        )
        self.padding = Theme.Spacing.MD
        self.bgcolor = ft.Colors.SURFACE_CONTAINER_HIGHEST
        self.border_radius = Theme.Components.CARD_RADIUS
        self.border = ft.border.all(0.5, ft.Colors.OUTLINE)


class OverviewTab(ft.Container):
    """Overview tab content combining existing sections."""

    def __init__(self, component_data: ComponentStatus) -> None:
        """
        Initialize overview tab.

        Args:
            component_data: ComponentStatus containing component health and metrics
        """
        super().__init__()

        metadata = component_data.metadata or {}

        self.content = ft.Column(
            [
                OverviewSection(metadata),
                ft.Container(
                    content=ServiceInfoSection(metadata),
                    padding=ft.padding.only(
                        left=Theme.Spacing.MD, right=Theme.Spacing.MD
                    ),
                ),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )


class AIDetailDialog(BaseDetailPopup):
    """
    AI service detail popup.

    Displays comprehensive AI service information including provider configuration,
    conversation statistics, usage metrics, and analytics in a tabbed interface.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the ai service details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
        """
        metadata = component_data.metadata or {}

        # Get engine for subtitle
        engine = metadata.get("engine", "AI Engine")
        engine_display_map = {
            "pydantic-ai": "Pydantic AI",
            "langchain": "LangChain",
        }
        subtitle = engine_display_map.get(
            engine, engine.replace("-", " ").title() if engine else "AI Engine"
        )

        # Build tabs list
        tabs_list = [
            ft.Tab(text="Overview", content=OverviewTab(component_data)),
        ]

        # Add Token Usage tab only if analytics is available (requires database backend)
        if AIAnalyticsTab is not None:
            tabs_list.append(
                ft.Tab(text="Token Usage", content=AIAnalyticsTab(metadata=metadata))
            )

        # Add Cloud Catalog tab
        if LLMCatalogTab is not None:
            tabs_list.append(ft.Tab(text="Cloud Catalog", content=LLMCatalogTab()))

        # Add Agents tab (agent registry requires database backend)
        if AgentsTab is not None:
            tabs_list.append(ft.Tab(text="Agents", content=AgentsTab()))

        # Add Memory Modules tab, right after Agents: an agent's definition
        # names the modules it uses, so the two are read together.
        if MemoryModulesTab is not None:
            tabs_list.append(ft.Tab(text="Memory", content=MemoryModulesTab()))

        # Add RAG tab only if RAG service is enabled
        if RAGTab is not None:
            tabs_list.append(ft.Tab(text="RAG", content=RAGTab()))

        # Add Voice tab
        if VoiceSettingsTab is not None:
            tabs_list.append(ft.Tab(text="Voice", content=VoiceSettingsTab()))

        # Create tabbed interface
        tabs = PulseTabs(
            selected_index=0,
            tabs=tabs_list,
            expand=True,
        )

        # Initialize base popup with tabs (non-scrollable - tabs handle
        # their own scrolling)
        # Use larger dimensions for AI modal to accommodate multiple tabs
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_ai"),
            subtitle_text=subtitle,
            sections=[tabs],
            scrollable=False,
            width=1100,
            height=800,
            status_detail=get_status_detail(component_data),
        )
