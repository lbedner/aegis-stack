"""
Base Popup Component using Container + Stack Pattern

Provides a reusable popup/modal system with full control over borders,
overlays, and styling. Unlike AlertDialog, this Container-based approach
allows complete customization of visual properties.

Pattern inspired by ee-toolset's mobile sidebar overlay implementation.
"""

import flet as ft

from app.components.frontend.controls.text import H3Text
from app.components.frontend.theme import AegisTheme as Theme


class BasePopup(ft.Container):
    """
    Container-based popup with overlay and customizable styling.

    Uses ft.Stack to layer a semi-transparent backdrop over content,
    with the popup panel centered on top. Provides full control over
    borders, shadows, and dimensions.

    Features:
    - Semi-transparent backdrop overlay
    - Click-to-close on backdrop by default (opt-out per popup if needed)
    - Programmatic show()/hide() control
    - Customizable borders and shadows
    - Full Container property access

    Usage:
        popup = BasePopup(
            page=page,
            content=my_content,
            width=900,
            height=700,
            border=ft.border.all(2, ft.Colors.PRIMARY),
        )

        # Add to page's overlay
        page.overlay.append(popup)

        # Show/hide programmatically
        popup.show()
        popup.hide()
    """

    def __init__(
        self,
        page: ft.Page,
        content: ft.Control,
        width: int | None = None,
        height: int | None = None,
        border: ft.Border | None = None,
        border_radius: int | None = None,
        bgcolor: str | None = None,
        shadow: ft.BoxShadow | None = None,
        padding: int | ft.Padding | None = None,
        dismiss_on_backdrop: bool = True,
    ) -> None:
        """
        Initialize the base popup.

        Args:
            content: The content to display in the popup
            width: Popup width in pixels
            height: Popup height in pixels
            border: Border configuration (e.g., ft.border.all(1, ft.Colors.PRIMARY))
            border_radius: Border radius for rounded corners
            bgcolor: Background color
            shadow: BoxShadow for elevation effect
            padding: Padding around content
            dismiss_on_backdrop: When True (default), a click outside the
                panel closes the popup. Set False to require the explicit
                close affordance instead.
        """
        super().__init__()
        self.page = page
        self._dismiss_on_backdrop = dismiss_on_backdrop

        # Semi-transparent backdrop overlay
        self.overlay = ft.Container(
            content=None,  # Just background
            bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLACK),
            visible=False,
            expand=True,
            on_click=self._handle_backdrop_click,
        )

        # Actual popup panel with customizable styling
        # Click handler stops propagation so clicks inside don't close popup
        self.panel = ft.Container(
            # Text controls are plain (see controls/text.py): selection
            # is a property of the region, not of each Text.
            content=ft.SelectionArea(content=content),
            visible=False,
            width=width,
            height=height,
            bgcolor=bgcolor or ft.Colors.SURFACE,
            border=border,
            border_radius=border_radius,
            shadow=shadow,
            padding=padding,
            on_click=lambda e: None,  # Stop click propagation from panel content
        )

        # Stack layout for overlay + panel
        # Wrap panel in another container to enable centering
        # The wrapping container needs the click handler since it's on top
        self.content = ft.Stack(
            controls=[
                self.overlay,  # Background overlay (not needed for clicks anymore)
                ft.Container(
                    content=self.panel,
                    alignment=ft.alignment.center,  # Center the popup
                    expand=True,
                    on_click=self._handle_backdrop_click,  # Handle clicks outside panel
                ),
            ],
            expand=True,
        )

        # Initialize as invisible
        self.visible = False
        self.expand = True

    def show(self) -> None:
        """
        Show the popup with overlay.

        Note: Caller must call page.update() after this method.
        """
        self.visible = True
        self.overlay.visible = True
        self.panel.visible = True

    def hide(self) -> None:
        """
        Hide the popup and overlay.

        Note: Caller must call page.update() after this method.
        """
        self.visible = False
        self.overlay.visible = False
        self.panel.visible = False

    def close(self) -> None:
        """Hide the popup AND repaint.

        ``hide()`` deliberately leaves the repaint to the caller (it is
        used mid-build); every caller that just wants the popup gone then
        rewrote the same two lines, and one wrote ``self.open = False`` -
        an AlertDialog-ism that does nothing on a Container and left the
        popup on screen with a dead Cancel button.
        """
        self.hide()
        if self.page is not None:
            self.page.update()

    def _handle_backdrop_click(self, e: ft.ControlEvent) -> None:
        """Close popup when backdrop is clicked (not the panel itself)."""
        if not self._dismiss_on_backdrop:
            return
        # Only close if the click was on the backdrop container, not the panel
        # The event control should be the wrapping Container, not the panel
        if e.control == self.panel:
            # Click was on the panel, don't close
            return

        self.hide()
        if e.page:
            e.page.update()


class OverlayStyledDialog(BasePopup):
    """``StyledAlertDialog``'s exact visual chrome (bordered panel, title,
    body, right-aligned actions) - backed by ``BasePopup``'s Container/
    Stack + ``page.overlay`` mechanism instead of a real ``ft.AlertDialog``.

    Use this instead of ``StyledAlertDialog`` specifically when the
    dialog's own body hosts a ``page.overlay``-based popup of its own
    (this app's custom ``Dropdown`` control, controls/dropdown.py) - a
    real ``ft.AlertDialog`` renders through Flutter's Navigator/dialog
    route, a separate layer that always paints above ordinary page
    content INCLUDING ``page.overlay`` Stack children, regardless of
    append order. A ``Dropdown`` nested inside a real ``AlertDialog``
    therefore opens BEHIND the dialog instead of above it - confirmed
    live: the account-filter panel inside the Uncategorized dialog
    (``OverviewTab._open_uncategorized``) rendered behind the dialog
    instead of on top of it. Everything here - this dialog AND any
    ``Dropdown`` it hosts - lives in the SAME ``page.overlay`` Stack, so
    plain append-order z-ordering applies and nested Dropdown popups
    paint correctly on top, the same way ``OverviewTab``'s own account
    filter already works (nested in ``FinanceDetailDialog``, itself a
    ``BasePopup``, not an ``AlertDialog``).

    Caller owns the ``page.overlay.append`` + ``page.update()`` on first
    build (this control isn't auto-attached to the page the way
    ``page.open()`` handles an ``AlertDialog``) - then ``show()``/
    ``hide()`` for every open/close after that, same as any other
    ``BasePopup``.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        title: str,
        body: ft.Control,
        actions: list[ft.Control],
        width: int = 360,
    ) -> None:
        panel = ft.Column(
            [
                H3Text(title),
                body,
                ft.Row(
                    actions,
                    alignment=ft.MainAxisAlignment.END,
                    spacing=Theme.Spacing.SM,
                ),
            ],
            spacing=Theme.Spacing.MD,
            tight=True,
        )
        super().__init__(
            page=page,
            content=panel,
            width=width,
            padding=20,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
        )
