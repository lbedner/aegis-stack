"""The submit/cancel pair a form ends with."""

from collections.abc import Awaitable, Callable

import flet as ft

from app.components.frontend.controls.buttons import (
    ElevatedCancelButton,
    ElevatedUpdateButton,
)
from app.components.frontend.theme import AegisTheme as Theme


class FormActionButtons(ft.Row):
    """
    Save/Cancel button pair for forms.

    Features:
    - Uses existing ElevatedUpdateButton and ElevatedCancelButton
    - Shows loading state when saving=True
    - Consistent right-aligned layout
    """

    def __init__(
        self,
        on_save: Callable[[], Awaitable[None]],
        on_cancel: Callable[[], Awaitable[None]],
        save_text: str = "Save",
        cancel_text: str = "Cancel",
        saving: bool = False,
    ) -> None:
        """
        Initialize form action buttons.

        Args:
            on_save: Async callback when save button is clicked.
            on_cancel: Async callback when cancel button is clicked.
            save_text: Text for the save button.
            cancel_text: Text for the cancel button.
            saving: Whether save operation is in progress (shows loading).
        """
        self._on_save = on_save
        self._on_cancel = on_cancel
        self._save_text = save_text
        self._saving = saving

        # Create buttons
        self._cancel_button = ElevatedCancelButton(
            on_click_callable=on_cancel,
            text=cancel_text,
        )

        self._save_button = ElevatedUpdateButton(
            on_click_callable=self._handle_save,
            text=save_text if not saving else "Saving...",
        )
        self._save_button.disabled = saving

        super().__init__(
            controls=[
                self._cancel_button,
                self._save_button,
            ],
            spacing=Theme.Spacing.SM,
            alignment=ft.MainAxisAlignment.END,
        )

    async def _handle_save(self) -> None:
        """Handle save button click."""
        await self._on_save()

    def set_saving(self, saving: bool) -> None:
        """Update the saving state."""
        self._saving = saving
        self._save_button.disabled = saving
        self._save_button.text = self._save_text if not saving else "Saving..."
        if self.page:
            self._save_button.update()
