"""
Agents Tab Component

Manages the database-driven agent registry: lists agents (click a row to
edit its definition: persona, sampling, model pin, active flag). Backed
by /ai/agents.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    H2Text,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.form_fields import (
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.status_dot import status_dot
from app.components.frontend.theme import AegisTheme as Theme

from .base_popup import BasePopup

ACTIVE_DEFAULT_KEY = "__active_default__"
ACTIVE_DEFAULT_LABEL = "(active default)"
DEFAULT_CATEGORIES = ("general", "support", "ops", "research")


def agent_row_cells(agent: dict[str, Any]) -> list[str]:
    """Text cells for one agent row: name, model, tools, modules (pure)."""
    return [
        agent.get("name", agent.get("slug", "")),
        agent.get("model_id") or "active default",
        str(len(agent.get("tools", []))),
        str(len(agent.get("memory_modules", []))),
    ]


def agent_edit_payload(
    *,
    name: str,
    description: str,
    category: str,
    model_id: str,
    temperature: float,
    max_tokens: str,
    system_prompt: str,
    is_active: bool,
) -> dict[str, Any]:
    """Form values -> PATCH payload (pure). Raises ValueError on bad numbers.

    Empty model_id means "use the service's active model" (stored NULL);
    empty description/category store NULL.
    """
    return {
        "name": name.strip(),
        "description": description.strip() or None,
        "category": category.strip() or None,
        "model_id": model_id.strip() or None,
        "temperature": round(float(temperature), 2),
        "max_tokens": int(max_tokens),
        "system_prompt": system_prompt,
        "is_active": is_active,
    }


def category_options(
    agents: list[dict[str, Any]], current: str | None
) -> list[tuple[str, str]]:
    """Dropdown options: defaults + categories in use + the current one."""
    seen: set[str] = set(DEFAULT_CATEGORIES)
    for agent in agents:
        if agent.get("category"):
            seen.add(str(agent["category"]))
    if current:
        seen.add(current)
    return [(value, value) for value in sorted(seen)]


def model_options(
    models: list[dict[str, Any]] | None, current: str | None
) -> list[tuple[str, str]]:
    """Dropdown options: active-default sentinel + catalog + current pin."""
    options: list[tuple[str, str]] = [(ACTIVE_DEFAULT_KEY, ACTIVE_DEFAULT_LABEL)]
    ids: list[str] = []
    for model in models or []:
        model_id = model.get("model_id")
        if model_id and model_id not in ids:
            ids.append(model_id)
    if current and current not in ids:
        ids.insert(0, current)
    options.extend((model_id, model_id) for model_id in ids)
    return options


class AgentEditPopup(BasePopup):
    """Overseer-styled editor panel for one agent definition."""

    def __init__(
        self,
        page: ft.Page,
        agent: dict[str, Any],
        categories: list[tuple[str, str]],
        models: list[tuple[str, str]],
        on_saved: Any,
    ) -> None:
        self._slug = agent.get("slug", "")
        self._on_saved = on_saved

        self._name = FormTextField("Name", value=agent.get("name", ""), variant="pulse")
        self._category = FormDropdown(
            "Category",
            options=categories,
            value=agent.get("category") or "general",
            variant="pulse",
        )
        self._description = FormTextField(
            "Description", value=agent.get("description") or "", variant="pulse"
        )
        self._model_id = FormDropdown(
            "Model",
            options=models,
            value=agent.get("model_id") or ACTIVE_DEFAULT_KEY,
            variant="pulse",
            max_menu_height=320,
        )
        self._max_tokens = FormTextField(
            "Max tokens",
            value=str(agent.get("max_tokens", 1000)),
            variant="pulse",
            input_filter=ft.NumbersOnlyInputFilter(),
        )
        self._temperature_value = SecondaryText(
            f"{float(agent.get('temperature', 0.7)):.2f}", width=44
        )
        self._temperature = ft.Slider(
            min=0.0,
            max=2.0,
            divisions=40,
            value=float(agent.get("temperature", 0.7)),
            active_color=Theme.Colors.SUCCESS,
            on_change=self._on_temperature_change,
            expand=True,
        )
        self._system_prompt = FormTextField(
            "System prompt",
            value=agent.get("system_prompt", ""),
            multiline=True,
            min_lines=8,
            max_lines=14,
            variant="pulse",
        )
        self._active = ft.Switch(
            value=bool(agent.get("is_active", False)),
            active_color=Theme.Colors.SUCCESS,
        )

        grants = ", ".join(agent.get("tools", [])) or "(none)"
        modules = ", ".join(agent.get("memory_modules", [])) or "(none)"
        kbs = ", ".join(agent.get("knowledge_base_ids", [])) or "(none)"

        body = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                H2Text(f"Edit '{self._slug}'"),
                                SecondaryText("Agent definition"),
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
                                ft.Container(content=self._model_id, expand=2),
                                ft.Container(width=Theme.Spacing.SM),
                                ft.Container(content=self._max_tokens, expand=True),
                            ]
                        ),
                        ft.Column(
                            [
                                SecondaryText("TEMPERATURE", size=10),
                                ft.Row(
                                    [
                                        self._temperature,
                                        self._temperature_value,
                                    ],
                                    spacing=Theme.Spacing.SM,
                                ),
                            ],
                            spacing=2,
                        ),
                        self._system_prompt,
                        SecondaryText(
                            f"Tools: {grants}  |  Modules: {modules}  "
                            f"|  Knowledge bases: {kbs}"
                        ),
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

        # Same panel recipe as BaseDetailPopup so the editor sits flush
        # with the rest of the Overseer modals.
        super().__init__(
            page=page,
            content=ft.Container(content=body, padding=20, width=760, height=640),
            width=760,
            height=640,
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

    def _on_temperature_change(self, e: ft.ControlEvent) -> None:
        self._temperature_value.value = f"{float(e.control.value):.2f}"
        self._temperature_value.update()

    def _close(self) -> None:
        self.hide()
        if self in self.page.overlay:
            self.page.overlay.remove(self)
        self.page.update()

    async def _handle_save(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        try:
            raw_model = self._model_id.value
            payload = agent_edit_payload(
                name=self._name.value,
                description=self._description.value,
                category=self._category.value,
                model_id="" if raw_model == ACTIVE_DEFAULT_KEY else raw_model,
                temperature=float(self._temperature.value or 0.0),
                max_tokens=self._max_tokens.value,
                system_prompt=self._system_prompt.value,
                is_active=bool(self._active.value),
            )
        except ValueError:
            ErrorSnackBar("Max tokens must be a number.").launch(self.page)
            return

        api = get_session_state(self.page).api_client
        updated = await api.patch(f"/ai/agents/{self._slug}", json=payload)
        if updated is None:
            ErrorSnackBar("The agent update was rejected.").launch(self.page)
            return
        self._close()
        await self._on_saved()

    async def _handle_cancel(self) -> None:
        self._close()


class AgentsTab(ft.Container):
    """Agent registry management tab for the AI service modal."""

    def __init__(self) -> None:
        super().__init__()
        self._agents: list[dict[str, Any]] = []
        self._model_catalog: list[dict[str, Any]] = []
        self._content_column = ft.Column(
            [
                ft.Container(
                    content=SecondaryText("Loading agents..."),
                    alignment=ft.alignment.center,
                    padding=Theme.Spacing.LG,
                ),
            ],
            expand=True,
        )
        self.content = self._content_column
        self.padding = Theme.Spacing.MD
        self.expand = True

    def did_mount(self) -> None:
        self.page.run_task(self._load_agents)

    async def _load_agents(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        agents = await api.get("/ai/agents")
        if agents is None:
            self._render_error("Could not load the agent registry.")
            return
        self._agents = agents
        # The LLM catalog router only exists on some stacks; a 404 here
        # just means the model dropdown offers the current pin only.
        catalog = await api.get("/api/v1/llm/models", params={"limit": 200})
        self._model_catalog = catalog if isinstance(catalog, list) else []
        self._render_agents(agents)

    def _render_agents(self, agents: list[dict[str, Any]]) -> None:
        columns = [
            DataTableColumn("Agent", width=170, style="primary"),
            DataTableColumn("Model", width=170, style="secondary"),
            DataTableColumn("Tools", width=70, alignment="right", style="body"),
            DataTableColumn("Modules", width=80, alignment="right", style="body"),
            DataTableColumn("Status", width=60, alignment="center", style=None),
        ]

        rows: list[list[Any]] = []
        for agent in agents:
            is_active = bool(agent.get("is_active", False))
            rows.append(
                [
                    *agent_row_cells(agent),
                    status_dot(
                        Theme.Colors.SUCCESS if is_active else Theme.Colors.ERROR
                    ),
                ]
            )

        table = DataTable(
            columns=columns,
            rows=rows,
            empty_message="No agents in the registry yet.",
            on_row_click=self._on_row_click,
            row_tooltips=["Click to edit" for _ in agents],
        )

        self._content_column.controls = [
            H3Text("Agent Registry"),
            ft.Container(height=Theme.Spacing.SM),
            table,
        ]
        self._content_column.scroll = ft.ScrollMode.AUTO
        self.update()

    def _on_row_click(self, index: int) -> None:
        if not 0 <= index < len(self._agents):
            return
        agent = self._agents[index]
        popup = AgentEditPopup(
            self.page,
            agent,
            categories=category_options(self._agents, agent.get("category")),
            models=model_options(self._model_catalog, agent.get("model_id")),
            on_saved=self._load_agents,
        )
        self.page.overlay.append(popup)
        popup.show()
        # BasePopup.show() defers rendering to the caller; without this
        # the popup only appears on the next unrelated page refresh.
        self.page.update()

    def _render_error(self, message: str) -> None:
        self._content_column.controls = [
            ft.Container(
                content=ft.Icon(
                    ft.Icons.ERROR_OUTLINE, size=48, color=Theme.Colors.ERROR
                ),
                alignment=ft.alignment.center,
                padding=Theme.Spacing.MD,
            ),
            ft.Container(
                content=H3Text("Failed to load agents"),
                alignment=ft.alignment.center,
            ),
            ft.Container(
                content=SecondaryText(message),
                alignment=ft.alignment.center,
            ),
        ]
        self._content_column.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.update()
