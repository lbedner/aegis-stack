"""Pending changes on the finance modal: proposals must outlive the chat.

The card is the SAME control the conversation renders
(``controls/chat/components``) - one renderer, one truth, two surfaces.
A proposal made in a chat that was closed still gets decided here: the
full queue lives on Review > Approvals, and Overview carries only the
one-line ``PendingChangesBanner`` pointing at it - proposals are never
invisible, and never bury the summary page either.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import SecondaryText
from app.components.frontend.controls.chat.components import render_component
from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.components.frontend.controls.text import H3Text
from app.components.frontend.dashboard.modals.modal_sections import (
    EmptyStatePlaceholder,
)
from app.components.frontend.theme import AegisTheme as Theme


class PendingChangesSection(ft.Container):
    """The approvals queue: every pending proposal, newest first.

    With an ``empty_message`` it is a queue's HOME (Review > Approvals):
    always visible, an empty state like every queue beside it. Without
    one it behaves as an embedded section that hides when empty.
    """

    def __init__(self, page: ft.Page, *, empty_message: str | None = None) -> None:
        super().__init__(visible=empty_message is not None)
        self.page = page
        self._empty_message = empty_message
        # Cards flow as a wrapping grid: a queue tab has vertical room,
        # and a sideways scroll hides everything past the first card.
        self._cards = ft.Row(
            [],
            spacing=Theme.Spacing.SM,
            wrap=True,
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

    def did_mount(self) -> None:
        if self.page:
            self.page.run_task(self.refresh)

    def refresh_on_revisit(self) -> None:
        """Dialog revisit hook: a proposal filed while another tab was
        open must be here when this one shows again."""
        if self.page:
            self.page.run_task(self.refresh)

    async def refresh(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        listing = await api.get("/api/v1/finance/changes")
        items = listing.get("items", []) if isinstance(listing, dict) else []
        self._render_items(items)

    def _render_items(self, items: list[dict[str, Any]]) -> None:
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
        if not controls and self._empty_message is not None:
            controls = [EmptyStatePlaceholder(message=self._empty_message)]
        self._cards.controls = controls
        self.visible = (
            bool(controls) if self._empty_message is None else True
        )
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


def pending_banner_label(count: int) -> str:
    noun = "change" if count == 1 else "changes"
    return f"{count} pending {noun} awaiting your approval"


class PendingChangesBanner(ft.Container):
    """Overview's one-line pointer at the approvals queue.

    Visible only while something is pending; clicking it jumps to
    Review > Approvals when a jump target is wired. The queue itself
    never renders here - that is the whole point.
    """

    def __init__(
        self, page: ft.Page, *, on_open_review: Callable[[], None] | None = None
    ) -> None:
        super().__init__(visible=False)
        self.page = page
        self._label = SecondaryText("", color=Theme.Colors.TEXT_PRIMARY)
        hint = "Review and approve"
        self.content = ft.Row(
            [
                ft.Icon(
                    ft.Icons.FACT_CHECK_OUTLINED,
                    size=16,
                    color=Theme.Colors.ACCENT,
                ),
                self._label,
                ft.Container(expand=True),
                SecondaryText(hint, color=Theme.Colors.ACCENT),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.padding = ft.padding.symmetric(
            horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
        )
        self.border_radius = Theme.Components.CARD_RADIUS
        self.bgcolor = ft.Colors.with_opacity(0.12, Theme.Colors.ACCENT)
        if on_open_review is not None:
            self.ink = True
            self.tooltip = "Open Review > Approvals"
            self.on_click = lambda _event: on_open_review()

    def show_count(self, count: int) -> None:
        self._label.value = pending_banner_label(count)
        self.visible = count > 0
        if self.page:
            self.update()

    async def refresh(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        listing = await api.get("/api/v1/finance/changes")
        items = listing.get("items", []) if isinstance(listing, dict) else []
        self.show_count(len(items))
