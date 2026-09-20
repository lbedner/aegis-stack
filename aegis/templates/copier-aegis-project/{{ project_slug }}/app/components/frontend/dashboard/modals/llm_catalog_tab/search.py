"""Searching the catalog, and what a result looks like."""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme

from ..modal_sections import SectionHeader
from .formatting import (
    _format_context,
    _format_price,
)


class ModelSearchSection(ft.Container):
    """Model search with filters and results table."""

    def __init__(
        self,
        vendors: list[str],
        modalities: list[str],
        page: ft.Page,
        on_switched: Any = None,
    ) -> None:
        super().__init__()

        self.page = page
        self._vendors = vendors
        self._modalities = modalities
        self._on_switched = on_switched

        # Search input
        self._search_input = ft.TextField(
            hint_text="Search models by name...",
            expand=True,
            border_radius=Theme.Components.INPUT_RADIUS,
            border_color=ft.Colors.OUTLINE,
            text_size=13,
            on_submit=self._on_search,
        )

        # Vendor dropdown
        vendor_options = [ft.dropdown.Option("", "All Vendors")]
        for v in vendors:
            vendor_options.append(ft.dropdown.Option(v))
        self._vendor_dropdown = ft.Dropdown(
            label="Vendor",
            options=vendor_options,
            value="",
            width=150,
            border_radius=Theme.Components.INPUT_RADIUS,
            border_color=ft.Colors.OUTLINE,
            text_size=13,
        )

        # Modality dropdown
        modality_options = [ft.dropdown.Option("", "All Modalities")]
        for m in modalities:
            modality_options.append(ft.dropdown.Option(m))
        self._modality_dropdown = ft.Dropdown(
            label="Modality",
            options=modality_options,
            value="",
            width=150,
            border_radius=Theme.Components.INPUT_RADIUS,
            border_color=ft.Colors.OUTLINE,
            text_size=13,
        )

        # Search button
        self._search_button = ft.OutlinedButton(
            text="Search",
            icon=ft.Icons.SEARCH,
            icon_color=ft.Colors.ON_SURFACE_VARIANT,
            style=ft.ButtonStyle(
                color=ft.Colors.ON_SURFACE_VARIANT,
                side=ft.BorderSide(1, ft.Colors.ON_SURFACE_VARIANT),
                shape=ft.RoundedRectangleBorder(radius=Theme.Components.INPUT_RADIUS),
            ),
            on_click=self._on_search_click,
        )

        # Results container
        self._results_container = ft.Column([], spacing=Theme.Spacing.XS)

        # Status text
        self._status_text = ft.Container(
            content=SecondaryText("Enter a search term or select filters"),
            visible=True,
        )

        # Loading indicator
        self._loading = ft.Container(
            content=ft.Row(
                [
                    ft.ProgressRing(width=20, height=20, stroke_width=2),
                    SecondaryText("Searching..."),
                ],
                spacing=Theme.Spacing.SM,
            ),
            visible=False,
        )

        # Build layout
        search_row = ft.Row(
            [
                self._search_input,
                self._vendor_dropdown,
                self._modality_dropdown,
                self._search_button,
            ],
            spacing=Theme.Spacing.SM,
        )

        self.content = ft.Column(
            [
                SectionHeader("Model Search"),
                ft.Container(height=Theme.Spacing.SM),
                search_row,
                ft.Container(height=Theme.Spacing.SM),
                self._loading,
                self._status_text,
                self._results_container,
            ],
            spacing=0,
        )
        self.padding = Theme.Spacing.MD

    async def _on_search(self, e: ft.ControlEvent) -> None:
        await self._do_search()

    async def _on_search_click(self, e: ft.ControlEvent) -> None:
        await self._do_search()

    async def _do_search(self) -> None:
        pattern = self._search_input.value
        vendor = self._vendor_dropdown.value
        modality = self._modality_dropdown.value

        # Require at least one filter
        if not pattern and not vendor and not modality:
            self._show_status("Please enter a search term or select a filter")
            return

        await self._execute_search(pattern, vendor, modality)

    def _show_status(self, message: str) -> None:
        self._status_text.content = SecondaryText(message)
        self._status_text.visible = True
        self._results_container.controls = []
        self.update()

    async def _execute_search(
        self, pattern: str | None, vendor: str | None, modality: str | None
    ) -> None:
        self._loading.visible = True
        self._status_text.visible = False
        self._results_container.controls = []
        self.update()

        try:
            params: dict[str, Any] = {"limit": 25}
            if pattern:
                params["pattern"] = pattern
            if vendor:
                params["vendor"] = vendor
            if modality:
                params["modality"] = modality

            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            models = await api.get("/api/v1/llm/models", params=params)
            self._loading.visible = False
            if not isinstance(models, list):
                self._show_status("Search failed.")
                return
            if not models:
                self._show_status("No models found")
            else:
                self._display_results(models)

        except Exception as e:
            self._loading.visible = False
            self._show_status(f"Error: {e!s}")

    def _use_handler(self, model_id: str) -> Any:
        """A click handler bound to one model id."""

        async def _handler(_e: ft.ControlEvent) -> None:
            await self._switch_to(model_id)

        return _handler

    async def _switch_to(self, model_id: str) -> None:
        """Make ``model_id`` the active model, then refresh what is shown."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.post("/api/v1/llm/current", json={"model_id": model_id})
        if not isinstance(response, dict) or not response.get("success"):
            message = "Could not switch model"
            if isinstance(response, dict) and response.get("message"):
                message = str(response["message"])
            self._show_status(message)
            self.update()
            return

        self._show_status(str(response.get("message") or f"Now using {model_id}"))
        self.update()
        if self._on_switched is not None:
            await self._on_switched()

    def _display_results(self, models: list[dict[str, Any]]) -> None:
        # Define columns
        columns = [
            DataTableColumn("Model"),  # expands
            DataTableColumn("Vendor", width=100),
            DataTableColumn("Context", width=70, alignment="right"),
            DataTableColumn("In $/M", width=70, alignment="right"),
            DataTableColumn("Out $/M", width=70, alignment="right"),
            DataTableColumn("", width=44, alignment="center"),
        ]

        # Build row data
        rows: list[list[ft.Control]] = []
        for model in models:
            model_id = model.get("model_id", "")
            vendor = model.get("vendor", "")
            context = model.get("context_window", 0)
            input_price = model.get("input_price")
            output_price = model.get("output_price")

            rows.append(
                [
                    ft.Text(
                        model_id,
                        size=12,
                        weight=ft.FontWeight.W_500,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=model_id,
                    ),
                    SecondaryText(vendor, size=12),
                    SecondaryText(_format_context(context), size=12),
                    SecondaryText(_format_price(input_price), size=12),
                    SecondaryText(_format_price(output_price), size=12),
                    ft.IconButton(
                        icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                        icon_size=18,
                        tooltip=f"Use {model_id}",
                        on_click=self._use_handler(model_id),
                    ),
                ]
            )

        # Build table with scrolling
        table = DataTable(
            columns=columns,
            rows=rows,
            row_padding=8,
            scroll_height=250,
            empty_message="No models found",
        )

        self._status_text.visible = False
        self._results_container.controls = [table]
        self.update()
