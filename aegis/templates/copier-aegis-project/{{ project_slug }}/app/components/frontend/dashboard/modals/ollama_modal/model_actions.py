"""The two controls in the models table that do something.

One makes a model the active one; the other pulls or unloads it. Both
reach back into the dialog to refresh it once the server has agreed,
which is why they take one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft
from app.components.frontend.controls import (
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.theme import AegisTheme as Theme

if TYPE_CHECKING:
    from .dialog import OllamaDetailDialog


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


class ModelActionButton(ft.Container):
    """Load or unload a model, with its own progress and error states.

    One class rather than two: LoadModelButton and UnloadModelButton ran
    to 163 lines that differed in the verb, the label, the button
    variant, and which OllamaClient method they called.
    """

    def __init__(
        self,
        model_name: str,
        page: ft.Page,
        ollama_url: str,
        dialog: OllamaDetailDialog | None = None,
        *,
        action: str = "load",
    ) -> None:
        """
        Args:
            model_name: Name of the model to act on
            page: Flet page instance for updates
            ollama_url: Ollama server URL
            dialog: Parent dialog, refreshed after the action succeeds
            action: ``"load"`` or ``"unload"``
        """
        super().__init__()
        self._model_name = model_name
        self._page = page
        self._ollama_url = ollama_url
        self._dialog = dialog
        self._action = action
        # Only under the pointer: an action button on every row turns the
        # table into a wall of controls and buries the data it describes.
        self.reveal_on_hover = True
        self.content = PulseButton(
            on_click_callable=self._on_click,
            text=action.capitalize(),
            # Unload is the destructive-ish one and reads amber; load
            # takes PulseButton's own default rather than passing None,
            # which the button rejects outright.
            variant="amber" if action == "unload" else "teal",
            compact=True,
        )

    def _failed(self, text: str) -> PulseButton:
        """The button becomes its own retry."""
        return PulseButton(
            on_click_callable=self._on_click,
            text=text,
            variant="stop",
            compact=True,
        )

    async def _on_click(self) -> None:
        """Run the action, showing progress and leaving a retry on failure."""
        self.content = ft.Row(
            [
                ft.ProgressRing(width=16, height=16, stroke_width=2),
                SecondaryText(
                    f"{self._action.capitalize()}ing...", color=Theme.Colors.ACCENT
                ),
            ],
            spacing=4,
        )
        self._page.update()

        try:
            from app.services.ai.domains.llm.ollama import OllamaClient

            client = OllamaClient(base_url=self._ollama_url)
            run = getattr(client, f"{self._action}_model")
            if await run(self._model_name):
                if self._dialog:
                    await self._dialog.refresh_data()
            else:
                self.content = self._failed("Failed")
        except Exception:
            self.content = self._failed("Error")

        self._page.update()
