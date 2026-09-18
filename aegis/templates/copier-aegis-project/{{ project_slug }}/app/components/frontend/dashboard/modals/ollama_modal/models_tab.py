"""The Models tab: every installed model, one row each.

The rows are built here because only this tab has the data; the cells
they are made of come from ``cells``, and the two controls that act on
a model from ``model_actions``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import flet as ft
from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.data_table import (
    CELL_ELLIPSIS_KWARGS,
    DataTable,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from .cells import (
    build_modified_cell,
    capability_cell,
    format_context_length,
    format_model_id,
    format_quantization,
    model_cell,
)
from .columns import CAPABILITIES, MODEL_COLUMNS
from .model_actions import ModelActionButton, UseModelControl

if TYPE_CHECKING:
    from .dialog import OllamaDetailDialog


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
                # Eleven columns is a lot to carry for someone who only
                # wants to see what is warm. The picker is the existing
                # escape hatch every other table here uses, rather than a
                # second bespoke density control.
                column_picker=True,
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
            context_length = details.get("context_length", 0)
            capabilities = model.get("capabilities", []) or []

            # No cold-model dimming. Painting every cold row at half
            # opacity meant that with nothing loaded - the normal state -
            # the whole table rendered washed out and read as a rendering
            # fault rather than as information. Warm/cold is already
            # carried by the VRAM figure and the Load/Unload button.
            name_text = TableNameText(model_name, **CELL_ELLIPSIS_KWARGS)
            params_text = model_cell(parameter_size or "—", numeric=True)
            quant_text = model_cell(format_quantization(quantization))
            # Tabular face: the short digest is a fixed-width token and
            # reads as one only if the glyphs line up.
            id_text = model_cell(format_model_id(model.get("digest", "")), numeric=True)
            context_text = model_cell(
                format_context_length(context_length), numeric=True
            )
            cap_cells = [
                capability_cell(cap.key in capabilities) for cap in CAPABILITIES
            ]
            modified_text = build_modified_cell(model.get("modified_at", ""))
            size_text = model_cell(f"{size_gb:.1f}G", numeric=True)

            # VRAM: show value for warm, dash for cold
            vram_display = f"{vram_gb:.1f}G" if is_warm and vram_gb is not None else "—"
            vram_text = model_cell(vram_display, numeric=True)

            # Unload a warm model, load a cold one.
            status_control: ft.Control = ModelActionButton(
                model_name=model_name,
                page=page,
                ollama_url=ollama_url,
                dialog=dialog,
                action="unload" if is_warm else "load",
            )

            rows.append(
                [
                    name_text,
                    id_text,
                    params_text,
                    quant_text,
                    context_text,
                    *cap_cells,
                    size_text,
                    modified_text,
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
            # Empty cells for alignment; only the VRAM column carries a
            # total, since it is the one figure that sums across rows.
            rows.append(
                [
                    total_label,
                    SecondaryText(""),  # ID
                    SecondaryText(""),  # Params
                    SecondaryText(""),  # Quant
                    SecondaryText(""),  # Context
                    *(SecondaryText("") for _ in CAPABILITIES),
                    SecondaryText(""),  # Size
                    SecondaryText(""),  # Modified
                    total_value,  # VRAM
                    SecondaryText(""),  # Status
                    SecondaryText(""),  # Active
                ]
            )

        return rows


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
