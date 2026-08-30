"""Pending changes on the finance modal: proposals must outlive the chat.

The card is the SAME control the conversation renders
(``controls/chat/components``) - one renderer, one truth, two surfaces.
A proposal made in a chat that was closed still gets decided here.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.chat.components import render_component
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.text import H3Text
from app.components.frontend.theme import AegisTheme as Theme


class PendingChangesSection(ft.Container):
    """The modal's queue view: every pending proposal, newest first.

    Invisible when the queue is empty - an empty approvals box would
    nag about a kind of event most sessions don't have.
    """

    def __init__(self, page: ft.Page) -> None:
        super().__init__(visible=False)
        self.page = page
        # A horizontal rail, not a column: approvals sit side by side
        # above the page and scroll sideways on overflow, instead of
        # pushing the charts down.
        self._cards = ft.Row(
            [],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        H3Text("Pending changes"),
                        SecondaryText(
                            "Proposed by your assistant - nothing runs until you approve"
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._cards,
            ],
            spacing=Theme.Spacing.SM,
            tight=True,
        )

    async def refresh(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        listing = await api.get("/api/v1/finance/changes")
        items = listing.get("items", []) if isinstance(listing, dict) else []
        # A 30-row batch proposed in chat is ONE card here too: group by
        # batch, singles stay singles - same renderers as the chat.
        batches: dict[str, list[dict[str, Any]]] = {}
        singles: list[dict[str, Any]] = []
        for item in items:
            if item.get("batch_id"):
                batches.setdefault(item["batch_id"], []).append(item)
            else:
                singles.append(item)
        controls: list[ft.Control] = []
        for batch_id, batch_items in batches.items():
            card = render_component(
                "pending_change_batch",
                {
                    "batch_id": batch_id,
                    "title": batch_items[0].get("title"),
                    "items": batch_items,
                },
                on_action=self._resolve,
                on_batch_action=self._resolve_batch,
                fetch_items=self._fetch_batch,
            )
            if card is not None:
                controls.append(card)
        for item in singles:
            card = render_component("pending_change", item, on_action=self._resolve)
            if card is not None:
                controls.append(card)
        self._cards.controls = controls
        self.visible = bool(self._cards.controls)
        if self.page:
            self.update()

    async def _resolve(self, change_id: int, action: str) -> dict[str, Any] | None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.post(f"/api/v1/finance/changes/{change_id}/{action}")
        if not isinstance(response, dict):
            ErrorSnackBar(api.last_error or "Could not resolve the change.").launch(
                self.page
            )
            return None
        return response

    async def _fetch_batch(self, batch_id: str) -> list[dict[str, Any]] | None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.get(f"/api/v1/finance/changes/batch/{batch_id}")
        return response.get("items") if isinstance(response, dict) else None

    async def _resolve_batch(
        self, batch_id: str, action: str, exclude_ids: list[int]
    ) -> dict[str, Any] | None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        response = await api.post(
            f"/api/v1/finance/changes/batch/{batch_id}/{action}",
            json={"exclude_ids": exclude_ids} if action == "approve" else None,
        )
        if not isinstance(response, dict):
            ErrorSnackBar(api.last_error or "Could not resolve the batch.").launch(
                self.page
            )
            return None
        return response
