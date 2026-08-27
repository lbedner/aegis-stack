"""Saved facts: the other half of the AI modal's Memory tab.

Memory modules are what the system assembles for an agent; these are what
the user told it. Facts are written by the ``save_memory`` tool mid
conversation and injected into every later turn, which makes an unreviewable
store a liability: a number the model misheard would be quoted back
confidently for months. This section lists them, corrects them, and forgets
them, over ``/api/v1/ai/user-memory``.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    H3Text,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.form_fields import FormDropdown, FormTextField
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time

from .base_popup import BasePopup

FACTS_ENDPOINT = "/api/v1/ai/user-memory"
EM_DASH = "—"


def fact_row_cells(fact: dict[str, Any], *, now_iso: str | None = None) -> list[str]:
    """Text cells for one saved fact: category, the fact, how long ago (pure)."""
    from datetime import datetime

    now = datetime.fromisoformat(now_iso) if now_iso else None
    saved_at = fact.get("saved_at")
    return [
        str(fact.get("category") or "general"),
        str(fact.get("fact") or ""),
        format_relative_time(saved_at, now=now, coarse=True) if saved_at else EM_DASH,
    ]


def fact_edit_payload(*, fact: str, category: str) -> dict[str, str]:
    """Form values -> PATCH payload (pure). Raises ValueError on a blank fact.

    Blank is rejected rather than stored: an empty edit reads as a delete the
    user did not ask for.
    """
    cleaned = fact.strip()
    if not cleaned:
        raise ValueError("A fact cannot be empty.")
    return {"fact": cleaned, "category": category}


class UserFactEditPopup(BasePopup):
    """Correct or forget one saved fact."""

    def __init__(
        self,
        page: ft.Page,
        fact: dict[str, Any],
        categories: list[str],
        on_changed: Any,
    ) -> None:
        self._page = page
        self._index = int(fact.get("index", 0))
        self._on_changed = on_changed

        self._fact = FormTextField(
            "Fact",
            value=str(fact.get("fact") or ""),
            multiline=True,
            min_lines=2,
            max_lines=6,
            variant="pulse",
        )
        self._category = FormDropdown(
            "Category",
            options=[(name, name) for name in categories],
            value=str(fact.get("category") or "general"),
            variant="pulse",
        )

        body = ft.Column(
            [
                PrimaryText(
                    "Edit saved fact",
                    weight=Theme.Typography.WEIGHT_SEMIBOLD,
                ),
                SecondaryText(
                    "Saved by the assistant during a conversation and read "
                    "back into every later one."
                ),
                ft.Container(height=Theme.Spacing.SM),
                self._fact,
                self._category,
                ft.Container(
                    content=ft.Row(
                        [
                            PulseButton(
                                on_click_callable=self._handle_forget,
                                text="Forget",
                                variant="stop",
                                compact=True,
                            ),
                            ft.Container(expand=True),
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
            tight=True,
        )

        super().__init__(
            page=page,
            content=ft.Container(content=body, padding=20, width=560),
            width=560,
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

    async def _handle_cancel(self) -> None:
        self.close()

    async def _handle_save(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        try:
            payload = fact_edit_payload(
                fact=self._fact.value or "",
                category=str(self._category.value or "general"),
            )
        except ValueError as exc:
            ErrorSnackBar(str(exc)).launch(self._page)
            return

        api = get_session_state(self._page).api_client
        response = await api.patch(f"{FACTS_ENDPOINT}/{self._index}", json=payload)
        if not isinstance(response, dict):
            ErrorSnackBar("Could not save that change.").launch(self._page)
            return

        self.close()
        await self._on_changed()

    async def _handle_forget(self) -> None:
        ConfirmDialog(
            page=self._page,
            title="Forget this fact?",
            message="The assistant will stop knowing it in future conversations.",
            confirm_text="Forget",
            destructive=True,
            on_confirm=self._delete,
        ).show()

    async def _delete(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self._page).api_client
        response = await api.delete(f"{FACTS_ENDPOINT}/{self._index}")
        if not isinstance(response, dict):
            ErrorSnackBar("Could not forget that fact.").launch(self._page)
            return

        self.close()
        await self._on_changed()


class UserFactsSection(ft.Column):
    """Lists saved facts; a row opens the editor."""

    def __init__(self) -> None:
        super().__init__(spacing=0, tight=True)
        self._facts: list[dict[str, Any]] = []
        self._categories: list[str] = []
        self._table_slot = ft.Container()
        self.controls = [
            H3Text("Saved Facts"),
            SecondaryText(
                "Durable facts the assistant saved from conversation, read "
                "back into every later turn. Correct one here and it stops "
                "being repeated."
            ),
            ft.Container(height=Theme.Spacing.SM),
            self._table_slot,
        ]

    async def load(self, page: ft.Page) -> None:
        """Fetch and render. Called by the tab once it is mounted."""
        from app.components.frontend.state.session_state import get_session_state
        from app.services.ai.domains.chat.user_memory import MEMORY_CATEGORIES

        self._categories = list(MEMORY_CATEGORIES)
        api = get_session_state(page).api_client
        response = await api.get(FACTS_ENDPOINT)
        if not isinstance(response, dict):
            self._table_slot.content = PrimaryText("Could not load saved facts.")
            self._table_slot.update()
            return

        self._facts = list(response.get("facts") or [])
        self._render()

    def _render(self) -> None:
        columns = [
            DataTableColumn("Category", width=110, style="secondary"),
            DataTableColumn("Fact", style="primary"),
            DataTableColumn("Saved", width=120, alignment="right", style="secondary"),
        ]
        self._table_slot.content = DataTable(
            columns=columns,
            rows=[fact_row_cells(fact) for fact in self._facts],
            empty_message="Nothing saved yet. Tell the assistant a fact it "
            "cannot read from your accounts.",
            on_row_click=self._on_row_click,
        )
        self._table_slot.update()

    def _on_row_click(self, index: int) -> None:
        if not 0 <= index < len(self._facts):
            return
        popup = UserFactEditPopup(
            self.page,
            self._facts[index],
            self._categories,
            on_changed=self._reload,
        )
        self.page.overlay.append(popup)
        popup.show()
        # BasePopup.show() defers rendering to the caller.
        self.page.update()

    async def _reload(self) -> None:
        await self.load(self.page)
