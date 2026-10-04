"""The change queue's HTTP calls, shared by every surface that renders
approval cards (the chat panel, Finance > Review).

The endpoints are the shared propose/approve queue's, which resolve
every service's change types; a stack without the queue never renders
a card that could call these.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls.snack_bar import ErrorSnackBar

PATH = "/api/v1/changes"


class ChangeApi:
    """The calls, bound to the control that hosts the cards: its page is
    read at call time, so the binding works before the control mounts."""

    def __init__(self, host: ft.Control) -> None:
        self._host = host

    def _client(self) -> Any:
        from app.components.frontend.state.session_state import get_session_state

        return get_session_state(self._host.page).api_client

    def _checked(self, response: Any, api: Any, what: str) -> dict[str, Any] | None:
        if isinstance(response, dict):
            return response
        ErrorSnackBar(api.last_error or f"Could not resolve the {what}.").launch(
            self._host.page
        )
        return None

    async def fetch(self, change_id: int) -> dict[str, Any] | None:
        response = await self._client().get(f"{PATH}/{change_id}")
        return response if isinstance(response, dict) else None

    async def resolve(self, change_id: int, action: str) -> dict[str, Any] | None:
        """Resolve one change and hand the card the queue's new truth."""
        api = self._client()
        response = await api.post(f"{PATH}/{change_id}/{action}")
        return self._checked(response, api, "change")

    async def fetch_batch(self, batch_id: str) -> list[dict[str, Any]] | None:
        response = await self._client().get(f"{PATH}/batch/{batch_id}")
        return response.get("items") if isinstance(response, dict) else None

    async def resolve_batch(
        self, batch_id: str, action: str, exclude_ids: list[int]
    ) -> dict[str, Any] | None:
        api = self._client()
        response = await api.post(
            f"{PATH}/batch/{batch_id}/{action}",
            json={"exclude_ids": exclude_ids} if action == "approve" else None,
        )
        return self._checked(response, api, "batch")
