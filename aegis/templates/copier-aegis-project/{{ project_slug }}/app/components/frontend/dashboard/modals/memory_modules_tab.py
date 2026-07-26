"""
Memory Modules Tab Component

Manages the database-driven memory-module registry: lists modules (click a row
to edit one) and previews what a module actually renders into an agent's
context. Backed by /api/v1/ai/memory-modules.

The preview is the point. A module's content is either static text or the
output of a registered fetcher, and in the fetcher case the row shows only a
function name - there is no way to tell a working module from a silently empty
one without rendering it.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    H3Text,
    PrimaryText,
    SecondaryText,
    ThemedSwitch,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.status_dot import status_dot
from app.components.frontend.theme import AegisTheme as Theme

from .base_popup import BasePopup

STATIC_SOURCE = "static text"
FETCHER_SOURCE = "fetcher"
BOTH_SOURCES = "static + fetcher"
NO_SOURCE = "none"


def module_source_label(module: dict[str, Any]) -> str:
    """Where a module's content comes from (pure).

    Named rather than implied, because "static" and "fetched" fail in
    completely different ways: static text is wrong in the database, a fetcher
    is wrong in code or unregistered entirely.
    """
    has_static = bool((module.get("prompt_content") or "").strip())
    has_fetcher = bool((module.get("fetch_function") or "").strip())
    if has_static and has_fetcher:
        return BOTH_SOURCES
    if has_fetcher:
        return FETCHER_SOURCE
    if has_static:
        return STATIC_SOURCE
    return NO_SOURCE


def module_row_cells(module: dict[str, Any]) -> list[str]:
    """Text cells for one module row: name, context key, source, priority."""
    return [
        module.get("name", module.get("slug", "")),
        module.get("context_key") or module.get("slug", ""),
        module_source_label(module),
        str(module.get("priority", 0)),
    ]


def module_edit_payload(
    *,
    name: str,
    description: str,
    category: str,
    context_key: str,
    prompt_content: str,
    fetch_function: str,
    priority: str,
    token_estimate: str,
    is_active: bool,
) -> dict[str, Any]:
    """Form values -> PATCH payload (pure). Raises ValueError on bad numbers.

    Empty text fields clear their column (stored NULL). The service enforces
    the real invariant - a module must keep at least one content source - so
    this only has to report the numbers honestly.
    """
    return {
        "name": name.strip(),
        "description": description.strip() or None,
        "category": category.strip() or None,
        "context_key": context_key.strip() or None,
        "prompt_content": prompt_content.strip() or None,
        "fetch_function": fetch_function.strip() or None,
        "priority": int(priority),
        "token_estimate": int(token_estimate),
        "is_active": is_active,
    }


class MemoryModuleEditPopup(BasePopup):
    """Edit one module's definition, with a live preview of what it renders."""

    def __init__(
        self,
        page: ft.Page,
        module: dict[str, Any],
        on_saved: Any,
    ) -> None:
        self._page = page
        self._slug = str(module.get("slug", ""))
        self._on_saved = on_saved

        self._name = FormTextField(
            "Name", value=str(module.get("name") or ""), variant="pulse"
        )
        self._category = FormTextField(
            "Category", value=str(module.get("category") or ""), variant="pulse"
        )
        self._description = FormTextField(
            "Description",
            value=str(module.get("description") or ""),
            variant="pulse",
        )
        self._context_key = FormTextField(
            "Context key",
            value=str(module.get("context_key") or ""),
            variant="pulse",
        )
        self._fetch_function = FormTextField(
            "Fetcher",
            value=str(module.get("fetch_function") or ""),
            variant="pulse",
        )
        self._prompt_content = FormTextField(
            "Static content",
            value=str(module.get("prompt_content") or ""),
            multiline=True,
            min_lines=4,
            max_lines=10,
            variant="pulse",
        )
        self._priority = FormTextField(
            "Priority", value=str(module.get("priority", 100)), variant="pulse"
        )
        self._token_estimate = FormTextField(
            "Token estimate",
            value=str(module.get("token_estimate", 0)),
            variant="pulse",
        )
        self._active = ThemedSwitch(value=bool(module.get("is_active", True)))

        self._preview = SecondaryText("")
        self._preview_box = ft.Container(
            content=ft.Column([self._preview], scroll=ft.ScrollMode.AUTO),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(0.5, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            padding=ft.padding.all(Theme.Spacing.MD),
            height=200,
            visible=False,
        )

        body = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                PrimaryText(
                                    f"Edit '{module.get('name') or self._slug}'",
                                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                                ),
                                SecondaryText(
                                    f"Memory module  |  {self._slug}  |  "
                                    f"{module_source_label(module)}"
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        ft.Row(
                            [SecondaryText("Active"), self._active],
                            spacing=Theme.Spacing.SM,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(height=Theme.Spacing.SM),
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Container(content=self._name, expand=True),
                                ft.Container(width=Theme.Spacing.SM),
                                ft.Container(content=self._category, expand=True),
                            ]
                        ),
                        self._description,
                        ft.Row(
                            [
                                ft.Container(content=self._context_key, expand=True),
                                ft.Container(width=Theme.Spacing.SM),
                                ft.Container(
                                    content=self._fetch_function, expand=True
                                ),
                            ]
                        ),
                        self._prompt_content,
                        ft.Row(
                            [
                                ft.Container(content=self._priority, expand=True),
                                ft.Container(width=Theme.Spacing.SM),
                                ft.Container(
                                    content=self._token_estimate, expand=True
                                ),
                            ]
                        ),
                        ft.Row(
                            [
                                SecondaryText("RENDERED CONTEXT", size=10),
                                ft.Container(expand=True),
                                PulseButton(
                                    on_click_callable=self._handle_preview,
                                    text="Preview",
                                    variant="muted",
                                    compact=True,
                                ),
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        self._preview_box,
                    ],
                    spacing=Theme.Spacing.SM,
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            PulseButton(
                                on_click_callable=self._handle_cancel,
                                text="Cancel",
                                variant="muted",
                                compact=True,
                            ),
                            PulseButton(
                                on_click_callable=self._handle_save,
                                text="Save",
                                compact=True,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=Theme.Spacing.SM,
                    ),
                    padding=ft.padding.only(top=10),
                ),
            ],
            spacing=10,
            expand=True,
        )

        super().__init__(
            page=page,
            content=ft.Container(content=body, padding=20, width=940, height=760),
            width=940,
            height=760,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )

    async def _handle_preview(self) -> None:
        """Render the module the way an agent turn would and show the text."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self._page).api_client
        response = await api.get(f"/api/v1/ai/memory-modules/{self._slug}/preview")
        if not isinstance(response, dict):
            ErrorSnackBar("Could not render this module.").launch(self._page)
            return
        # An empty render is the interesting case: the module is wired up but
        # contributed nothing, which a table row can never show.
        self._preview.value = response.get("rendered") or (
            "This module rendered nothing. A fetcher that is unregistered, or "
            "that found no data for this user, contributes no context."
        )
        self._preview_box.visible = True
        if self._preview_box.page is not None:
            self._preview_box.update()

    def _close(self) -> None:
        self.open = False
        if self.page is not None:
            self.page.update()

    async def _handle_save(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        try:
            payload = module_edit_payload(
                name=self._name.value or "",
                description=self._description.value or "",
                category=self._category.value or "",
                context_key=self._context_key.value or "",
                prompt_content=self._prompt_content.value or "",
                fetch_function=self._fetch_function.value or "",
                priority=self._priority.value or "0",
                token_estimate=self._token_estimate.value or "0",
                is_active=bool(self._active.value),
            )
        except ValueError:
            ErrorSnackBar(
                "Priority and token estimate must be whole numbers."
            ).launch(self._page)
            return

        api = get_session_state(self._page).api_client
        response = await api.patch(
            f"/api/v1/ai/memory-modules/{self._slug}", json=payload
        )
        if not isinstance(response, dict):
            ErrorSnackBar(
                "Could not save. A module needs static content or a fetcher."
            ).launch(self._page)
            return

        self._close()
        if self._on_saved is not None:
            await self._on_saved()

    async def _handle_cancel(self) -> None:
        self._close()


class MemoryModulesTab(ft.Container):
    """The memory-module registry: what an agent can be handed as context."""

    def __init__(self) -> None:
        super().__init__()
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._modules: list[dict[str, Any]] = []
        self._content_column = ft.Column(
            [SecondaryText("Loading memory modules...")],
            spacing=0,
            expand=True,
        )
        self.content = self._content_column

    def did_mount(self) -> None:
        if self.page:
            self.page.run_task(self._load_modules)

    async def _load_modules(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        modules = await api.get("/api/v1/ai/memory-modules")
        if not isinstance(modules, list):
            self._render_error("Could not load memory modules.")
            return
        self._modules = modules
        self._render_modules(modules)

    def _render_modules(self, modules: list[dict[str, Any]]) -> None:
        columns = [
            DataTableColumn("Module", width=190, style="primary"),
            DataTableColumn("Context key", width=170, style="secondary"),
            DataTableColumn("Source", width=130, style="secondary"),
            DataTableColumn("Priority", width=70, alignment="right", style="body"),
            DataTableColumn("Status", width=60, alignment="center", style=None),
        ]

        rows: list[list[Any]] = []
        for module in modules:
            is_active = bool(module.get("is_active", False))
            rows.append(
                [
                    *module_row_cells(module),
                    status_dot(
                        Theme.Colors.SUCCESS if is_active else Theme.Colors.ERROR
                    ),
                ]
            )

        table = DataTable(
            columns=columns,
            rows=rows,
            empty_message="No memory modules registered yet.",
            on_row_click=self._on_row_click,
        )

        self._content_column.controls = [
            H3Text("Memory Modules"),
            SecondaryText(
                "Reusable blocks of context an agent opts into. Lower priority "
                "renders first, and a module is dropped when it will not fit "
                "the turn's token budget."
            ),
            ft.Container(height=Theme.Spacing.SM),
            table,
        ]
        self._content_column.scroll = ft.ScrollMode.AUTO
        self.update()

    def _on_row_click(self, index: int) -> None:
        if not 0 <= index < len(self._modules):
            return
        popup = MemoryModuleEditPopup(
            self.page,
            self._modules[index],
            on_saved=self._load_modules,
        )
        self.page.overlay.append(popup)
        popup.show()
        # BasePopup.show() defers rendering to the caller; without this the
        # popup only appears on the next unrelated page refresh.
        self.page.update()

    def _render_error(self, message: str) -> None:
        self._content_column.controls = [PrimaryText(message)]
        self.update()
