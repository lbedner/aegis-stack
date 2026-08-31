"""The chat panel's conversation-history dialog.

One mixin of ``ChatPanel``: the row builder and the dialog itself.
Split out for size, not concept - the panel stays the state owner.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.text import PrimaryText, SecondaryText
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time


class HistoryMixin:
    """List past conversations, pick one to reload."""

    # Provided by ChatPanel
    page: ft.Page
    surface: str | None
    user_id: str
    _history_dialog: StyledAlertDialog | None

    def _api(self) -> Any: ...  # real definition on ChatPanel

    async def _load_conversation(self, conversation_id: str) -> Any: ...

    def _history_row(self, conv: dict[str, Any]) -> ft.Control:
        async def pick() -> None:
            if self._history_dialog is not None:
                self._history_dialog.open = False
                self.page.update()
            await self._load_conversation(conv["id"])

        return ft.Container(
            content=ft.Column(
                [
                    PrimaryText(
                        conv.get("title") or conv["id"][:8],
                        no_wrap=True,
                        selectable=False,
                    ),
                    SecondaryText(
                        format_relative_time(conv.get("last_activity")),
                        size=Theme.Typography.BODY_SMALL,
                        selectable=False,
                    ),
                ],
                spacing=0,
                tight=True,
            ),
            padding=Theme.Spacing.SM,
            border_radius=Theme.Components.BUTTON_RADIUS,
            ink=True,
            on_click=lambda _event: self.page.run_task(pick),
        )

    async def _open_history(self) -> None:
        params: dict[str, Any] = {"user_id": self.user_id, "limit": 25}
        if self.surface:
            params["surface"] = self.surface
        conversations = await self._api().get("/api/v1/ai/conversations", params)
        rows: list[ft.Control] = [
            self._history_row(conv) for conv in (conversations or [])
        ]
        if not rows:
            rows = [SecondaryText("No conversations yet.")]

        async def _close_history() -> None:
            if self._history_dialog is not None:
                self._history_dialog.open = False
                self.page.update()

        self._history_dialog = StyledAlertDialog(
            title="Conversation history",
            body=ft.Container(
                content=ft.Column(rows, tight=True, scroll=ft.ScrollMode.AUTO),
                height=320,
            ),
            on_close=_close_history,
        )
        self.page.open(self._history_dialog)
