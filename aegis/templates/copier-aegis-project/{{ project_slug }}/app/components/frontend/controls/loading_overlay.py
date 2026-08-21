"""
Blocking loading overlay for the Overseer.

A full-page scrim with a spinner shown while an operation runs: every
click lands on the scrim, so nothing else can happen until the operation
finishes. The outcome is explicit - the overlay clears on success or
switches to an error panel showing what actually failed (selectable, so
it can be copied), instead of the failure dying as a log line behind a
generic toast.

Example::

    overlay = LoadingOverlay.of(page)
    overlay.show("Importing transactions...")
    ...
    overlay.hide()                            # success path
    overlay.fail(api.last_error or "Failed")  # stays up until Close
"""

from __future__ import annotations

import json
from typing import Any

import flet as ft
import httpx

from app.components.frontend.controls.busy_bar import busy_bar
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.text import BodyText, SecondaryText
from app.components.frontend.styles import ColorPalette, PulseColors

# SSE waits between events can be arbitrarily long (a cold local model
# loads for minutes before its first status change), so the job stream
# gets no read timeout - the terminal event is how it ends.
_SSE_TIMEOUT = httpx.Timeout(10.0, read=None)


class LoadingOverlay(ft.Container):
    """Page-wide modal scrim with a busy state and a terminal error state."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__()
        self._page = page
        self.visible = False
        self.expand = True
        self.bgcolor = ft.Colors.with_opacity(0.6, ft.Colors.BLACK)
        self.alignment = ft.alignment.center
        # Swallow clicks so nothing underneath is reachable while shown.
        self.on_click = lambda _e: None
        self._label = BodyText("", color=PulseColors.TEXT, weight=ft.FontWeight.W_600)
        self._panel = ft.Container(
            padding=24,
            bgcolor=PulseColors.CARD,
            border=ft.border.all(1, PulseColors.BORDER),
            border_radius=8,
            width=460,
        )
        self.content = self._panel

    @classmethod
    def of(cls, page: ft.Page) -> LoadingOverlay:
        """Session-wide instance, created and mounted into ``page.overlay``
        on first use."""
        if page.data is None:
            page.data = {}
        overlay = page.data.get("_loading_overlay")
        if overlay is None:
            overlay = cls(page)
            page.data["_loading_overlay"] = overlay
            page.overlay.append(overlay)
        return overlay

    def show(self, label: str) -> None:
        """Show the busy state and block the page until hide() or fail()."""
        self._label.value = label
        # Label above, bar beneath it spanning the panel: the bar is the
        # operation, not an ornament sitting next to its name. Every
        # blocking overlay in the app renders through here, so this is the
        # one place the busy affordance is chosen.
        # tight, or the Column stretches to all available height and the
        # panel renders as a viewport-tall box with the label pinned at
        # the top (confirmed live). The error panel below already knows.
        self._panel.content = ft.Column(
            [
                self._label,
                busy_bar(),
            ],
            spacing=16,
            tight=True,
        )
        self._raise_to_top()
        self.visible = True
        self._page.update()

    def update_label(self, label: str) -> None:
        """Change the busy message without rebuilding the panel."""
        self._label.value = label
        self._page.update()

    def hide(self) -> None:
        """Clear the overlay (the success path)."""
        self.visible = False
        self._page.update()

    def fail(self, message: str, *, title: str = "Operation failed") -> None:
        """Switch to the error state; stays up until the user closes it.

        ``message`` should be the real failure reason (e.g.
        ``APIClient.last_error``), rendered selectable so it can be copied
        into a bug report or terminal.
        """
        icon_circle = ft.Container(
            content=ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.WHITE, size=16),
            width=28,
            height=28,
            border_radius=14,
            bgcolor=ColorPalette.ACCENT_STOP,
            alignment=ft.alignment.center,
        )
        self._panel.content = ft.Column(
            [
                ft.Row(
                    [
                        icon_circle,
                        BodyText(
                            title, color=PulseColors.TEXT, weight=ft.FontWeight.W_600
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                # Scrolls beyond ~5 lines so a long traceback-ish message
                # cannot grow the panel past the viewport.
                ft.Container(
                    content=ft.Column(
                        [
                            SecondaryText(
                                message, color=PulseColors.MUTED, selectable=True
                            )
                        ],
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    height=None if len(message) < 400 else 180,
                    padding=ft.padding.only(left=40),
                ),
                ft.Row(
                    [
                        PulseButton(
                            on_click_callable=self._close,
                            text="Close",
                            variant="muted",
                            compact=True,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=16,
            tight=True,
        )
        self._raise_to_top()
        self.visible = True
        self._page.update()

    async def run_job(
        self, api: Any, job_id: str, *, title: str = "Operation failed"
    ) -> dict[str, Any] | None:
        """Follow a server job's SSE stream until it lands.

        The generic long-operation flow: an endpoint called with
        ``background=true`` returned ``{"job_id": ...}``; this keeps the
        (already shown) overlay's label in sync with the job's status
        events, then either clears the overlay and returns the job's
        result, or shows the job's real error and returns None.

        ``api`` is the session APIClient (its cookie jar rides along).
        """
        endpoint = f"/api/v1/jobs/{job_id}/events"
        try:
            async with api.stream("GET", endpoint, timeout=_SSE_TIMEOUT) as response:
                if response.status_code != 200:
                    self.fail(
                        f"Could not follow the job (HTTP {response.status_code}).",
                        title=title,
                    )
                    return None
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    snapshot = json.loads(line[len("data:") :])
                    status = snapshot.get("status")
                    if status == "running":
                        label = snapshot.get("label")
                        if label:
                            self.update_label(label)
                        continue
                    if status == "done":
                        self.hide()
                        return snapshot.get("result") or {}
                    self.fail(
                        snapshot.get("error") or "The operation failed.", title=title
                    )
                    return None
        except Exception as e:
            self.fail(f"Lost the job stream: {e}", title=title)
            return None
        self.fail("The job stream ended without a result.", title=title)
        return None

    async def _close(self) -> None:
        self.hide()

    def _raise_to_top(self) -> None:
        # Later ``page.overlay`` entries render on top. Modals and file
        # pickers may have been appended after this overlay was created,
        # so re-append before showing to guarantee it covers everything.
        overlay_list = self._page.overlay
        if overlay_list and overlay_list[-1] is not self:
            if self in overlay_list:
                overlay_list.remove(self)
            overlay_list.append(self)
