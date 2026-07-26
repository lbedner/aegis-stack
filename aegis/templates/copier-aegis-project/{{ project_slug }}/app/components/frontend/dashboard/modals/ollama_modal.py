"""
Ollama Detail Modal

Displays comprehensive Ollama local LLM infrastructure information including
running models, VRAM usage, installed models, and server configuration.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    H3Text,
    NumericText,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.data_table import DataTable, DataTableColumn
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.log import logger
from app.services.ai.ollama_activity import get_ollama_activity
from app.services.system.models import ComponentStatus

from ..activity_feed import format_relative_time
from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .modal_sections import MetricCard

# Statistics section layout
STAT_LABEL_WIDTH = 200

# How often the open modal re-checks Ollama. The /api/ps probe is a local
# sub-100ms call, so this is cheap; it exists because Ollama evicts idle
# models on its own (keep_alive expiry) and there is no event to listen for.
POLL_INTERVAL_SECONDS = 10.0

# Model table column widths
COL_WIDTH_MODEL_NAME = 180
COL_WIDTH_PARAMS = 60
COL_WIDTH_QUANT = 50
COL_WIDTH_SIZE = 65
COL_WIDTH_VRAM = 65
COL_WIDTH_STATUS = 80
COL_WIDTH_ACTIVE = 70

# Model table columns for DataTable
MODEL_COLUMNS = [
    DataTableColumn("Model", width=COL_WIDTH_MODEL_NAME, style="body"),
    DataTableColumn("Params", width=COL_WIDTH_PARAMS, style="secondary"),
    DataTableColumn("Quant", width=COL_WIDTH_QUANT, style="secondary"),
    DataTableColumn("Size", width=COL_WIDTH_SIZE, alignment="right", style="secondary"),
    DataTableColumn("VRAM", width=COL_WIDTH_VRAM, alignment="right", style="secondary"),
    DataTableColumn("Status", width=COL_WIDTH_STATUS),
    DataTableColumn("Active", width=COL_WIDTH_ACTIVE),
]

# Activity table columns for DataTable
ACTIVITY_COLUMNS = [
    DataTableColumn("Model", width=COL_WIDTH_MODEL_NAME, style="body"),
    DataTableColumn("Event", width=90),
    DataTableColumn("VRAM", width=COL_WIDTH_VRAM, alignment="right", style="secondary"),
    DataTableColumn("Source", width=80, style="secondary"),
    DataTableColumn("When", width=140, style="secondary"),
]

ACTIVITY_EVENT_LABELS = {
    "loaded": "Loaded",
    "unloaded": "Unloaded",
    "evicted": "Evicted",
}

ACTIVITY_EVENT_COLORS = {
    "loaded": Theme.Colors.SUCCESS,
    "unloaded": Theme.Colors.WARNING,
    "evicted": Theme.Colors.TEXT_SECONDARY,
}


def format_quantization(quant: str) -> str:
    """Convert quantization level to human-readable format.

    Q4_K_M → 4-bit
    Q8_0 → 8-bit
    Q5_K_S → 5-bit
    """
    if not quant or quant == "—":
        return "—"
    # Extract the bit number from formats like Q4_K_M, Q8_0, Q5_K_S
    if quant.startswith("Q") and len(quant) > 1:
        bit_num = quant[1]
        if bit_num.isdigit():
            return f"{bit_num}-bit"
    return quant


class UseModelControl(ft.Container):
    """Make a local model the one the app answers with.

    Loading a model into VRAM and *using* it are different things: Ollama can
    hold several at once, while the app answers with exactly one. This is the
    second half - the Cloud Catalog tab does the same job for catalog models,
    and both go through the same endpoint.
    """

    def __init__(
        self,
        model_name: str,
        page: ft.Page,
        is_active: bool,
        dialog: OllamaDetailDialog | None = None,
    ) -> None:
        super().__init__()
        self._model_name = model_name
        self._page = page
        self._dialog = dialog

        if is_active:
            self.content = SecondaryText(
                "Active",
                color=Theme.Colors.SUCCESS,
            )
            return

        self.content = PulseButton(
            on_click_callable=self._on_use_click,
            text="Use",
            compact=True,
        )

    async def _on_use_click(self) -> None:
        """Switch the app to this model, then refresh the table."""
        from app.components.frontend.state.session_state import get_session_state

        self.content = SecondaryText("Switching...", color=Theme.Colors.ACCENT)
        self.update()

        api = get_session_state(self._page).api_client
        response = await api.post(
            "/api/v1/llm/current", json={"model_id": self._model_name}
        )
        if not isinstance(response, dict) or not response.get("success"):
            self.content = SecondaryText("Failed", color=Theme.Colors.ERROR)
            self.update()
            return

        if self._dialog is not None:
            await self._dialog.refresh_data()
            return
        self.content = SecondaryText("Active", color=Theme.Colors.SUCCESS)
        self.update()


class LoadModelButton(ft.Container):
    """Load button for cold models with loading state and error handling."""

    def __init__(
        self,
        model_name: str,
        page: ft.Page,
        ollama_url: str,
        dialog: OllamaDetailDialog | None = None,
    ) -> None:
        """
        Initialize load model button.

        Args:
            model_name: Name of the model to load
            page: Flet page instance for updates
            ollama_url: Ollama server URL
            dialog: Parent dialog for refreshing data after model load
        """
        super().__init__()
        self._model_name = model_name
        self._page = page
        self._ollama_url = ollama_url
        self._dialog = dialog
        # Only under the pointer: a Load button on every row turns the table
        # into a wall of controls and buries the data it is meant to describe.
        self.reveal_on_hover = True

        self._button = PulseButton(
            on_click_callable=self._on_load_click,
            text="Load",
            compact=True,
        )
        self.content = self._button

    async def _on_load_click(self) -> None:
        """Handle Load button click - warm up the model."""
        # Pin visible: a spinner that disappears the moment the pointer moves
        # off the row looks like the click did nothing.
        self.reveal_on_hover = False
        self.opacity = 1
        # Show loading spinner
        self.content = ft.Row(
            [
                ft.ProgressRing(width=16, height=16, stroke_width=2),
                SecondaryText("Loading...", color=Theme.Colors.ACCENT),
            ],
            spacing=4,
        )
        self._page.update()

        # Load the model asynchronously
        try:
            from app.services.ai.ollama import OllamaClient

            client = OllamaClient(base_url=self._ollama_url)
            success = await client.load_model(self._model_name)

            if success:
                # Model loaded - refresh the entire modal with fresh health data
                if self._dialog:
                    await self._dialog.refresh_data()
            else:
                # Failed to load - show error with retry button
                self.content = PulseButton(
                    on_click_callable=self._on_load_click,
                    text="Failed",
                    variant="stop",
                    compact=True,
                )
        except Exception:
            # Error - show with retry option
            self.content = PulseButton(
                on_click_callable=self._on_load_click,
                text="Error",
                variant="stop",
                compact=True,
            )

        self._page.update()


class UnloadModelButton(ft.Container):
    """Unload button for warm models with loading state and error handling."""

    def __init__(
        self,
        model_name: str,
        page: ft.Page,
        ollama_url: str,
        dialog: OllamaDetailDialog | None = None,
    ) -> None:
        """
        Initialize unload model button.

        Args:
            model_name: Name of the model to unload
            page: Flet page instance for updates
            ollama_url: Ollama server URL
            dialog: Parent dialog for refreshing data after model unload
        """
        super().__init__()
        self._model_name = model_name
        self._page = page
        self._ollama_url = ollama_url
        self._dialog = dialog
        self.reveal_on_hover = True

        self._button = PulseButton(
            on_click_callable=self._on_unload_click,
            text="Unload",
            variant="amber",
            compact=True,
        )
        self.content = self._button

    async def _on_unload_click(self) -> None:
        """Handle Unload button click - remove model from VRAM."""
        # Pin visible: a spinner that disappears the moment the pointer moves
        # off the row looks like the click did nothing.
        self.reveal_on_hover = False
        self.opacity = 1
        # Show loading spinner
        self.content = ft.Row(
            [
                ft.ProgressRing(width=16, height=16, stroke_width=2),
                SecondaryText("...", color=Theme.Colors.WARNING),
            ],
            spacing=4,
        )
        self._page.update()

        # Unload the model asynchronously
        try:
            from app.services.ai.ollama import OllamaClient

            client = OllamaClient(base_url=self._ollama_url)
            success = await client.unload_model(self._model_name)

            if success:
                # Model unloaded - refresh the entire modal with fresh health data
                if self._dialog:
                    await self._dialog.refresh_data()
            else:
                # Failed to unload - show error with retry button
                self.content = PulseButton(
                    on_click_callable=self._on_unload_click,
                    text="Failed",
                    variant="stop",
                    compact=True,
                )
        except Exception:
            # Error - show with retry option
            self.content = PulseButton(
                on_click_callable=self._on_unload_click,
                text="Error",
                variant="stop",
                compact=True,
            )

        self._page.update()


class OverviewSection(ft.Container):
    """Overview section showing key Ollama metrics."""

    def __init__(self, ollama_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize overview section.

        Args:
            ollama_component: Ollama ComponentStatus with metadata
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ollama_component.metadata or {}

        running_models = metadata.get("running_models", [])
        running_count = metadata.get("running_models_count", 0)
        installed_count = metadata.get("installed_models_count", 0)
        total_vram_gb = metadata.get("total_vram_gb", 0.0)

        # Determine status color based on running models
        if running_count > 0:
            status_text = "Warm"
            status_color = Theme.Colors.SUCCESS
        elif installed_count > 0:
            status_text = "Cold"
            status_color = Theme.Colors.ACCENT
        else:
            status_text = "No models"
            status_color = Theme.Colors.WARNING

        # Metric cards row
        metrics_row = ft.Row(
            [
                MetricCard(
                    "VRAM Usage",
                    f"{total_vram_gb:.1f} GB",
                    Theme.Colors.SUCCESS if total_vram_gb > 0 else Theme.Colors.ACCENT,
                ),
                MetricCard(
                    "Models",
                    f"{running_count} / {installed_count}",
                    Theme.Colors.ACCENT,
                ),
                MetricCard(
                    "Status",
                    status_text,
                    status_color,
                ),
            ],
            spacing=Theme.Spacing.MD,
        )

        # Active models display (full width, below metrics) - show all warm models
        if running_models:
            model_tags = [
                Tag(rm.get("name", "Unknown"), color=Theme.Colors.SUCCESS)
                for rm in running_models
            ]
            active_model_row = ft.Container(
                content=ft.Row(
                    [
                        SecondaryText("Active Models:", width=110),
                        ft.Row(model_tags, spacing=Theme.Spacing.XS, wrap=True),
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.only(top=Theme.Spacing.MD),
            )
        else:
            active_model_row = ft.Container(
                content=ft.Row(
                    [
                        SecondaryText("Active Models:", width=110),
                        SecondaryText("None loaded", italic=True),
                    ],
                    spacing=Theme.Spacing.SM,
                ),
                padding=ft.padding.only(top=Theme.Spacing.MD),
            )

        self.content = ft.Column(
            [metrics_row, active_model_row],
            spacing=0,
        )


class ServerInfoSection(ft.Container):
    """Server information section showing connection details."""

    def __init__(self, ollama_component: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize server info section.

        Args:
            ollama_component: Ollama ComponentStatus with metadata
            page: Flet page instance
        """
        super().__init__()
        self.padding = Theme.Spacing.MD

        metadata = ollama_component.metadata or {}
        response_time = ollama_component.response_time_ms or 0

        base_url = metadata.get("base_url", "http://localhost:11434")
        version = metadata.get("version", "Unknown")
        available = metadata.get("available", False)

        def info_row(label: str, value: str) -> ft.Row:
            """Create an info row."""
            return ft.Row(
                [
                    SecondaryText(
                        f"{label}:",
                        weight=Theme.Typography.WEIGHT_SEMIBOLD,
                        width=STAT_LABEL_WIDTH,
                    ),
                    BodyText(value),
                ],
                spacing=Theme.Spacing.MD,
            )

        self.content = ft.Column(
            [
                H3Text("Server Information"),
                ft.Container(height=Theme.Spacing.SM),
                info_row("Base URL", base_url),
                info_row("Version", version if version else "Unknown"),
                info_row("Status", "Available" if available else "Unavailable"),
                info_row("Response Time", f"{response_time:.0f}ms"),
            ],
            spacing=Theme.Spacing.XS,
        )


class ModelsSection(ft.Container):
    """Models section showing all installed models with warm/cold status."""

    def __init__(
        self,
        ollama_component: ComponentStatus,
        page: ft.Page,
        dialog: OllamaDetailDialog | None = None,
    ) -> None:
        """
        Initialize models section.

        Args:
            ollama_component: Ollama ComponentStatus with installed_models
            page: Flet page instance
            dialog: Parent dialog for refreshing data after model load
        """
        super().__init__()
        self._dialog = dialog
        self.padding = Theme.Spacing.MD

        metadata = ollama_component.metadata or {}
        installed_models = metadata.get("installed_models", [])
        running_models = metadata.get("running_models", [])
        total_vram_gb = metadata.get("total_vram_gb", 0.0)
        ollama_url = metadata.get("base_url", "http://localhost:11434")

        # Build a map of running model names to their VRAM usage
        running_model_map: dict[str, float] = {}
        for rm in running_models:
            running_model_map[rm.get("name", "")] = rm.get("size_vram_gb", 0.0)

        # Build row data for DataTable (includes total VRAM row if applicable)
        rows = self._build_rows(
            installed_models, running_model_map, page, ollama_url, dialog, total_vram_gb
        )

        if rows:
            # Build table with data. The Total VRAM footer (present whenever
            # something is loaded) must stay put when a header sort reorders
            # the model rows.
            table = DataTable(
                columns=MODEL_COLUMNS,
                rows=rows,
                row_padding=6,
                show_header_border=True,
                show_row_borders=True,
                empty_message="No models installed",
                pinned_last_rows=1 if total_vram_gb > 0 else 0,
            )

            self.content = ft.Column([table], spacing=0)
        else:
            # Empty state
            self.content = ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(
                                    ft.Icons.DOWNLOAD,
                                    size=48,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                                SecondaryText("No models installed"),
                                SecondaryText(
                                    "Use 'ollama pull <model>' to install a model",
                                    size=Theme.Typography.CAPTION,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=Theme.Spacing.SM,
                        ),
                        alignment=ft.alignment.center,
                        expand=True,
                        padding=Theme.Spacing.LG,
                    ),
                ],
                spacing=0,
            )

    def _build_rows(
        self,
        installed_models: list[dict[str, Any]],
        running_model_map: dict[str, float],
        page: ft.Page,
        ollama_url: str,
        dialog: OllamaDetailDialog | None,
        total_vram_gb: float = 0.0,
    ) -> list[list[Any]]:
        """Build row data for DataTable.

        Args:
            installed_models: List of installed model dicts
            running_model_map: Map of running model names to VRAM usage
            page: Flet page instance
            ollama_url: Ollama server URL
            dialog: Parent dialog for refresh
            total_vram_gb: Total VRAM usage to show in footer row

        Returns:
            List of row data lists for DataTable
        """
        # The dashboard runs in the same process as the API, so the active
        # model is a plain settings read - no round trip. This is the value
        # the server will actually answer with.
        from app.core.config import settings

        active_model_id = getattr(settings, "AI_MODEL", None)

        rows: list[list[Any]] = []
        for model in installed_models:
            model_name = model.get("name", "")
            is_warm = model_name in running_model_map
            vram_gb = running_model_map.get(model_name)
            size_gb = model.get("size_gb", 0.0)
            details = model.get("details", {})
            parameter_size = details.get("parameter_size", "—")
            quantization = details.get("quantization_level", "—")

            # Apply opacity for cold models
            opacity = 1.0 if is_warm else 0.5

            # Build styled text controls with opacity
            name_text = TableNameText(model_name)
            name_text.opacity = opacity

            params_text = NumericText(
                parameter_size if parameter_size else "—",
                color=Theme.Colors.TEXT_SECONDARY,
            )
            params_text.opacity = opacity

            quant_text = SecondaryText(
                format_quantization(quantization),
            )
            quant_text.opacity = opacity

            size_text = NumericText(
                f"{size_gb:.1f}G",
                color=Theme.Colors.TEXT_SECONDARY,
            )
            size_text.opacity = opacity

            # VRAM: show value for warm, dash for cold
            vram_display = f"{vram_gb:.1f}G" if is_warm and vram_gb is not None else "—"
            vram_text = NumericText(
                vram_display,
                color=Theme.Colors.TEXT_SECONDARY,
            )
            vram_text.opacity = opacity

            # Status: Unload button for warm models, Load button for cold
            if is_warm:
                status_control: ft.Control = UnloadModelButton(
                    model_name=model_name,
                    page=page,
                    ollama_url=ollama_url,
                    dialog=dialog,
                )
            else:
                status_control = LoadModelButton(
                    model_name=model_name,
                    page=page,
                    ollama_url=ollama_url,
                    dialog=dialog,
                )

            rows.append(
                [
                    name_text,
                    params_text,
                    quant_text,
                    size_text,
                    vram_text,
                    status_control,
                    UseModelControl(
                        model_name=model_name,
                        page=page,
                        is_active=model_name == active_model_id,
                        dialog=dialog,
                    ),
                ]
            )

        # Add total VRAM footer row if any models are loaded
        if total_vram_gb > 0:
            total_label = SecondaryText(
                "Total VRAM",
                weight=Theme.Typography.WEIGHT_BOLD,
            )
            # Tabular face, so the total lines up under the column it sums.
            total_value = NumericText(
                f"{total_vram_gb:.1f}G",
                weight=Theme.Typography.WEIGHT_BOLD,
                color=Theme.Colors.TEXT_SECONDARY,
            )
            # Empty cells for alignment (Params, Quant, Size columns)
            rows.append(
                [
                    total_label,
                    SecondaryText(""),  # Params
                    SecondaryText(""),  # Quant
                    SecondaryText(""),  # Size
                    total_value,  # VRAM
                    SecondaryText(""),  # Status
                    SecondaryText(""),  # Active
                ]
            )

        return rows


class ActivitySection(ft.Container):
    """Recent model activity as a table, newest first.

    Reads the process-wide tracker directly (the dashboard runs in the
    same process as the API), so no round trip and no persistence: the
    log is ephemeral by design.
    """

    def __init__(self) -> None:
        super().__init__()
        self.padding = Theme.Spacing.MD
        # (control, timestamp) pairs so relative times can be re-rendered
        # in place on each poll tick without rebuilding the table.
        self._time_cells: list[tuple[SecondaryText, datetime]] = []

        events = get_ollama_activity().events()
        if not events:
            self.content = ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Icon(
                                    ft.Icons.HISTORY,
                                    size=48,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                                SecondaryText("No model activity yet"),
                                SecondaryText(
                                    "Loads, unloads, and evictions appear "
                                    "here as they happen",
                                    size=Theme.Typography.CAPTION,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=Theme.Spacing.SM,
                        ),
                        alignment=ft.alignment.center,
                        expand=True,
                        padding=Theme.Spacing.LG,
                    ),
                ],
                spacing=0,
            )
            return

        rows: list[list[Any]] = []
        for event in events:
            when_text = SecondaryText(format_relative_time(event.timestamp))
            self._time_cells.append((when_text, event.timestamp))
            vram_display = f"{event.vram_gb:.1f}G" if event.vram_gb else "—"
            rows.append(
                [
                    TableNameText(event.model),
                    Tag(
                        ACTIVITY_EVENT_LABELS[event.action],
                        color=ACTIVITY_EVENT_COLORS[event.action],
                    ),
                    NumericText(vram_display, color=Theme.Colors.TEXT_SECONDARY),
                    SecondaryText("Ollama" if event.detected else "App"),
                    when_text,
                ]
            )

        self.content = ft.Column(
            [
                DataTable(
                    columns=ACTIVITY_COLUMNS,
                    rows=rows,
                    row_padding=6,
                    show_header_border=True,
                    show_row_borders=True,
                ),
            ],
            spacing=0,
        )

    def refresh_times(self) -> None:
        """Re-render the relative timestamps so they age while the modal is open."""
        for text, timestamp in self._time_cells:
            text.value = format_relative_time(timestamp)


# =============================================================================
# Tab Containers
# =============================================================================


class OverviewTab(ft.Container):
    """Overview tab combining metrics and server info."""

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        super().__init__()
        self.content = ft.Column(
            [
                OverviewSection(component_data, page),
                ServerInfoSection(component_data, page),
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True


class ModelsTab(ft.Container):
    """Models tab showing all installed models with warm/cold status."""

    def __init__(
        self,
        component_data: ComponentStatus,
        page: ft.Page,
        dialog: OllamaDetailDialog | None = None,
    ) -> None:
        super().__init__()
        self.content = ft.Column(
            [ModelsSection(component_data, page, dialog=dialog)],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True


class ActivityTab(ft.Container):
    """Activity tab showing recent model loads, unloads, and evictions."""

    def __init__(self) -> None:
        super().__init__()
        self.section = ActivitySection()
        self.content = ft.Column(
            [self.section],
            scroll=ft.ScrollMode.AUTO,
        )
        self.padding = ft.padding.all(Theme.Spacing.SM)
        self.expand = True


# =============================================================================
# Main Dialog
# =============================================================================


def _data_snapshot(component_data: ComponentStatus) -> tuple[Any, ...]:
    """Hashable fingerprint of everything the modal renders.

    Used by the poll loop to skip rebuilds when nothing changed - a rebuild
    drops scroll position and hover state, so it should only happen on a
    real transition (model loaded/evicted, VRAM shifted, new activity).
    """
    from app.core.config import settings

    metadata = component_data.metadata or {}
    events = get_ollama_activity().events()
    return (
        component_data.status,
        metadata.get("version"),
        metadata.get("total_vram_gb"),
        tuple(
            sorted(
                (rm.get("name", ""), rm.get("size_vram_gb", 0.0))
                for rm in metadata.get("running_models", [])
            )
        ),
        tuple(sorted(m.get("name", "") for m in metadata.get("installed_models", []))),
        getattr(settings, "AI_MODEL", None),
        len(events),
        events[0].timestamp if events else None,
    )


class OllamaDetailDialog(BaseDetailPopup):
    """
    Ollama local LLM infrastructure detail popup dialog.

    Displays comprehensive Ollama information including running models,
    VRAM usage, and server configuration.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        """
        Initialize the Ollama details popup.

        Args:
            component_data: ComponentStatus containing component health and metrics
            page: Flet page instance
        """
        self._page = page
        self._component_data = component_data
        self._poll_task: asyncio.Task[None] | None = None
        self._snapshot = _data_snapshot(component_data)

        metadata = component_data.metadata or {}
        version = metadata.get("version", "")
        running_count = metadata.get("running_models_count", 0)

        # Build subtitle - show Ollama with version and model count
        subtitle = self._build_subtitle(version, running_count)

        # Build tabs - store references for refresh
        self._overview_tab = ft.Tab(
            text="Overview", content=OverviewTab(component_data, page)
        )
        self._models_tab = ft.Tab(
            text="Models", content=ModelsTab(component_data, page, dialog=self)
        )
        self._activity_tab = ft.Tab(text="Activity", content=ActivityTab())

        self._tabs = PulseTabs(
            selected_index=0,
            tabs=[self._overview_tab, self._models_tab, self._activity_tab],
            expand=True,
        )

        # Initialize base popup with tabs
        super().__init__(
            page=page,
            component_data=component_data,
            title_text="Inference",
            subtitle_text=subtitle,
            sections=[self._tabs],
            scrollable=False,
            width=700,
            height=550,
            status_detail=get_status_detail(component_data),
        )

    def _build_subtitle(self, version: str, running_count: int) -> str:
        """Build subtitle text based on version and running model count."""
        subtitle = f"Ollama v{version}" if version else "Ollama"
        if running_count > 0:
            status = f"{running_count} model{'s' if running_count > 1 else ''} loaded"
            subtitle = f"{subtitle} • {status}"
        return subtitle

    def show(self) -> None:
        """Show the popup and start the visibility-scoped poll loop."""
        super().show()
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = self._page.run_task(self._poll_while_visible)

    def hide(self) -> None:
        """Hide the popup and stop polling."""
        super().hide()
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    def update_data(self, component_data: ComponentStatus) -> None:
        """Adopt the dashboard's latest health snapshot on re-open.

        The modal is cached across opens (see ``_open_modal``), so without
        this a re-open would show whatever Ollama looked like the first
        time. The poll loop then re-fetches live data right after show().
        """
        self._snapshot = _data_snapshot(component_data)
        self._apply(component_data)

    async def _poll_while_visible(self) -> None:
        """Keep the modal in sync with Ollama while it is open.

        Ollama drops idle models on its own (``keep_alive`` expiry) and a
        chat request can warm one, so a modal that only refreshes after
        button clicks goes stale. The first tick runs immediately to catch
        anything that happened since the dialog was built or last shown.
        """
        while self.visible:
            try:
                await self.refresh_data(only_if_changed=True)
            except Exception as e:
                # A failing update means the page is gone (disconnect or
                # teardown); stop polling - show() restarts it next open.
                logger.debug(f"Ollama modal poll stopped: {e}")
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def refresh_data(self, *, only_if_changed: bool = False) -> None:
        """Refresh modal with fresh health data.

        Args:
            only_if_changed: Skip the tab rebuild when nothing the modal
                renders has changed. The poll loop passes True so scroll
                and hover state survive quiet ticks; the Load/Unload/Use
                buttons use the default and always rebuild.
        """
        from app.services.system.health import check_ollama_health

        fresh_status = await check_ollama_health()

        snapshot = _data_snapshot(fresh_status)
        if only_if_changed and snapshot == self._snapshot:
            # Nothing moved; just let the relative timestamps age.
            self._refresh_activity_times()
            self._page.update()
            return

        self._snapshot = snapshot
        self._apply(fresh_status)
        self._page.update()

    def _apply(self, fresh_status: ComponentStatus) -> None:
        """Rebuild the modal header and tabs from a health snapshot."""
        self._component_data = fresh_status

        # Update subtitle with fresh counts
        metadata = fresh_status.metadata or {}
        version = metadata.get("version", "")
        running_count = metadata.get("running_models_count", 0)
        new_subtitle = self._build_subtitle(version, running_count)

        # Update subtitle in title row (second element in title column)
        if self._title_row and len(self._title_row.controls) > 0:
            title_column = self._title_row.controls[0]
            if hasattr(title_column, "controls") and len(title_column.controls) > 1:
                title_column.controls[1].value = new_subtitle

        # Update the status badge in the header
        self.update_status(fresh_status.status, get_status_detail(fresh_status))

        # Preserve current tab selection
        current_tab_index = self._tabs.selected_index

        # Rebuild tab contents with fresh data
        self._overview_tab.content = OverviewTab(fresh_status, self._page)
        self._models_tab.content = ModelsTab(fresh_status, self._page, dialog=self)
        self._activity_tab.content = ActivityTab()

        # Restore tab selection
        self._tabs.selected_index = current_tab_index

    def _refresh_activity_times(self) -> None:
        """Update the Activity tab's relative timestamps in place."""
        content = self._activity_tab.content
        if isinstance(content, ActivityTab):
            content.section.refresh_times()
