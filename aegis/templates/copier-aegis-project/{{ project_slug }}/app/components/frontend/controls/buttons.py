"""
Professional button components for Aegis Stack dashboard.

Provides reusable, theme-aware button components with consistent styling,
hover effects, and semantic variants for common actions.
"""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

import flet as ft

from app.components.frontend import styles
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.snack_bar import SuccessSnackBar
from app.components.frontend.controls.text import BodyText

AsyncClickCallable = Callable[[], Awaitable[None]]


class BaseElevatedButton(ft.ElevatedButton):
    """
    Base elevated button with consistent styling and hover effects.

    Features:
    - Dramatic elevation changes on hover (4→8)
    - Fast animations (100ms)
    - Consistent height and padding
    - Theme-aware colors

    ``on_click_callable`` MUST be an ``async`` no-arg callable. Aegis is
    async-first; sync handlers are only allowed on the ``on_route`` page
    handler. A sync callable here will raise ``TypeError`` at click time
    because the dispatcher awaits the result.
    """

    def __init__(
        self,
        on_click_callable: AsyncClickCallable,
        style: ft.ButtonStyle,
        text: str,
        text_style: styles.ButtonTextStyle,
        *args,
        **kwargs,
    ) -> None:
        super().__init__()
        self.on_click_callable = on_click_callable
        self.style = style
        self.text = text
        self.text_style = text_style
        self.args = args
        self.content = ft.Text(self.text, **asdict(self.text_style))

        async def _dispatch_click(_: ft.ControlEvent) -> None:
            await self.on_click_callable()

        self.on_click = _dispatch_click
        self.on_hover = self.on_hover_event  # type: ignore[assignment]
        self.kwargs = kwargs
        self.height = 36  # Consistent button height

    def on_hover_event(self, e: ft.HoverEvent) -> None:
        """Handle hover events for visual feedback."""
        # Elevation changes handled by ButtonStyle
        if self.page:
            self.update()


class ElevatedAddButton(BaseElevatedButton):
    """Button for add/create actions."""

    def __init__(
        self, on_click_callable: Callable, text: str = "Add", **kwargs
    ) -> None:
        super().__init__(
            on_click_callable,
            style=styles.ELEVATED_BUTTON_ADD_STYLE,
            text=text,
            text_style=styles.AddButtonTextStyle,
            **kwargs,
        )


class ElevatedUpdateButton(BaseElevatedButton):
    """Button for update/edit actions."""

    def __init__(
        self, on_click_callable: Callable, text: str = "Update", **kwargs
    ) -> None:
        super().__init__(
            on_click_callable,
            style=styles.ELEVATED_BUTTON_UPDATE_STYLE,
            text=text,
            text_style=styles.UpdateButtonTextStyle,
            **kwargs,
        )


class ElevatedDeleteButton(BaseElevatedButton):
    """Button for delete/remove actions."""

    def __init__(
        self, on_click_callable: Callable, text: str = "Delete", **kwargs
    ) -> None:
        super().__init__(
            on_click_callable,
            style=styles.ELEVATED_BUTTON_DELETE_STYLE,
            text=text,
            text_style=styles.DeleteButtonTextStyle,
            **kwargs,
        )


class ElevatedCancelButton(BaseElevatedButton):
    """Button for cancel actions."""

    def __init__(
        self, on_click_callable: Callable, text: str = "Cancel", **kwargs
    ) -> None:
        super().__init__(
            on_click_callable,
            style=styles.ELEVATED_BUTTON_CANCEL_STYLE,
            text=text,
            text_style=styles.CancelButtonTextStyle,
            **kwargs,
        )


class ElevatedRefreshButton(BaseElevatedButton):
    """Button for refresh/reload actions."""

    def __init__(
        self, on_click_callable: Callable, text: str = "Refresh", **kwargs
    ) -> None:
        super().__init__(
            on_click_callable,
            style=styles.ELEVATED_BUTTON_REFRESH_STYLE,
            text=text,
            text_style=styles.RefreshButtonTextStyle,
            **kwargs,
        )


# PulseButton's own geometry, exported rather than inlined: a control that
# has to READ as one of these buttons but can't BE one takes its numbers
# from here instead of re-picking them. (``BulkActionTrigger`` in
# controls/pickers.py is the case - it needs ``on_tap_down`` to position a
# popup, which ElevatedButton doesn't expose, so it's a Container wearing
# this look. Hand-picked copies drift the first time the button changes.)
PULSE_BUTTON_HEIGHT = 40
PULSE_BUTTON_COMPACT_HEIGHT = 28
PULSE_BUTTON_COMPACT_RADIUS = 6
PULSE_BUTTON_COMPACT_PADDING = ft.padding.symmetric(horizontal=10, vertical=2)


class PulseButton(BaseElevatedButton):
    """Flat, accent-tinted button matching the Aegis Pulse web frontend look.

    Unlike the Elevated* family this button has no drop shadow — the
    visual weight comes from a 1px accent border and a translucent fill
    that deepens on hover. Pick a variant:

    - ``"teal"`` (default) — primary / brand action.
    - ``"amber"`` — secondary or highlight action.

    Example::

        PulseButton(on_click_callable=self._submit, text="Create")
        PulseButton(on_click_callable=self._flag, text="Flag", variant="amber")
    """

    _VARIANTS = {
        "teal": styles.PULSE_BUTTON_TEAL_STYLE,
        "amber": styles.PULSE_BUTTON_AMBER_STYLE,
        "muted": styles.PULSE_BUTTON_MUTED_STYLE,
        "stop": styles.PULSE_BUTTON_STOP_STYLE,
    }

    def __init__(
        self,
        on_click_callable: Callable,
        text: str,
        variant: str = "teal",
        compact: bool = False,
        **kwargs,
    ) -> None:
        self._compact = compact
        super().__init__(
            on_click_callable,
            style=self._build_style(variant),
            text=text,
            text_style=styles.PulseButtonTextStyle,
            **kwargs,
        )
        # Match Pulse's vertical rhythm (py-2.5 + text-sm → ~40px line box).
        # Compact uses a 28px line box for in-header use.
        self.height = PULSE_BUTTON_COMPACT_HEIGHT if compact else PULSE_BUTTON_HEIGHT

    def _build_style(self, variant: str) -> ft.ButtonStyle:
        base_style = self._VARIANTS.get(variant)
        if base_style is None:
            raise ValueError(
                f"Unknown PulseButton variant '{variant}'. "
                f"Must be one of: {', '.join(sorted(self._VARIANTS))}"
            )
        # Compact mode is a slimmer version for use inside card headers
        # or other dense layouts. Same colors / borders as the variant,
        # tighter padding, smaller corner radius.
        if not self._compact:
            return base_style
        return ft.ButtonStyle(
            color=base_style.color,
            bgcolor=base_style.bgcolor,
            side=base_style.side,
            shape=ft.RoundedRectangleBorder(radius=PULSE_BUTTON_COMPACT_RADIUS),
            padding=PULSE_BUTTON_COMPACT_PADDING,
            elevation=0,
            overlay_color=ft.Colors.TRANSPARENT,
            animation_duration=150,
        )

    def set_variant(self, variant: str) -> None:
        """Swap the colour variant at runtime, preserving compact mode.

        Useful for toggle-style buttons where the same control toggles
        between an inactive ("muted") and active ("teal" / "amber")
        appearance without changing the label or layout.
        """
        self.style = self._build_style(variant)
        if self.page:
            self.update()


class BaseIconButton(ft.IconButton):
    """
    Base icon button with theme-aware colors and disabled states.

    Features:
    - Theme-aware icon colors
    - Proper disabled state handling
    - Tooltip support
    - Optional parameter passing to click handler
    """

    def __init__(
        self,
        on_click_callable: Callable[..., Awaitable[None]],
        icon: str,
        icon_color: str | None = None,
        get_param_callable: Callable[[], Any] | None = None,
        tooltip: str | None = None,
        disabled: bool = False,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.on_click_callable = on_click_callable
        self.get_param_callable = get_param_callable
        self.icon = icon
        self.disabled_color = ft.Colors.OUTLINE  # Theme-aware disabled color

        # Use theme-aware color if none provided
        if icon_color is None:
            icon_color = ft.Colors.ON_SURFACE_VARIANT

        self.enabled_color = icon_color
        self.icon_color = self.enabled_color if not disabled else self.disabled_color
        self.default_tooltip = tooltip
        self.tooltip = tooltip if not disabled else None
        self.on_click = self.on_click_event
        self.disabled = disabled

    async def on_click_event(self, e: ft.ControlEvent) -> None:
        """Dispatch the async click handler. ``on_click_callable`` MUST be async."""
        if self.disabled:
            return
        param = self.get_param_callable() if self.get_param_callable else None
        if param:
            await self.on_click_callable(param)
        else:
            await self.on_click_callable()

    def update_state(self, disabled: bool) -> None:
        """Update button disabled state and visual appearance."""
        self.disabled = disabled
        self.tooltip = self.default_tooltip if not self.disabled else None
        self.icon_color = (
            self.enabled_color if not self.disabled else self.disabled_color
        )
        if self.page:
            self.update()


class IconAddButton(BaseIconButton):
    """Icon button for add actions."""

    def __init__(
        self, on_click_callable: Callable, disabled: bool = False, **kwargs
    ) -> None:
        super().__init__(
            on_click_callable,
            icon=ft.Icons.ADD_OUTLINED,
            tooltip="Add",
            disabled=disabled,
            **kwargs,
        )


class IconRefreshButton(BaseIconButton):
    """Icon button for refresh actions."""

    def __init__(
        self,
        on_click_callable: Callable,
        get_param_callable: Callable | None = None,
        disabled: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            on_click_callable,
            icon=ft.Icons.REFRESH_SHARP,
            get_param_callable=get_param_callable,
            tooltip="Refresh",
            disabled=disabled,
            **kwargs,
        )


class IconCopyButton(BaseIconButton):
    """Copies whatever ``get_text`` returns and confirms with a snack bar.
    Reads the text at click time, so it follows a body that keeps changing."""

    def __init__(self, get_text: Callable[[], str], **kwargs: Any) -> None:
        super().__init__(
            self._copy, icon=ft.Icons.CONTENT_COPY_OUTLINED, tooltip="Copy", **kwargs
        )
        self.get_text = get_text

    async def _copy(self) -> None:
        if self.page is None:
            return
        self.page.set_clipboard(self.get_text())
        SuccessSnackBar("Copied").launch(self.page)


class IconDeleteButton(BaseIconButton):
    """Icon button for delete actions."""

    def __init__(
        self,
        on_click_callable: Callable,
        get_param_callable: Callable | None = None,
        disabled: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            on_click_callable,
            icon=ft.Icons.DELETE_OUTLINED,
            get_param_callable=get_param_callable,
            tooltip="Delete",
            disabled=disabled,
            **kwargs,
        )


class ConfirmDialog(StyledAlertDialog):
    """
    Reusable confirmation dialog with consistent styling.

    Features:
    - Theme-aware styling
    - Cancel and Confirm buttons
    - Optional destructive mode (red confirm button)
    - Async callback support
    """

    def __init__(
        self,
        page: ft.Page,
        title: str,
        message: str,
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        on_confirm: AsyncClickCallable | None = None,
        destructive: bool = False,
        secondary_text: str | None = None,
        on_secondary: AsyncClickCallable | None = None,
        secondary_destructive: bool = False,
    ) -> None:
        """
        Initialize confirmation dialog.

        Args:
            page: Flet page instance
            title: Dialog title
            message: Dialog message/content
            confirm_text: Text for confirm button
            cancel_text: Text for cancel button
            on_confirm: Async callback when confirmed.
            destructive: If True, confirm button is styled as destructive (red)
            secondary_text: When set, renders a third button between
                Cancel and Confirm with this label.
            on_secondary: Async callback when the secondary button is clicked.
            secondary_destructive: If True, the secondary button uses
                the red destructive variant; otherwise it stays muted.
        """
        self._page = page
        self._on_confirm = on_confirm
        self._on_secondary = on_secondary

        # Compact buttons: dialog actions sit on a dense strip, and the
        # full 40px line box reads heavy there (same call BaseDetailPopup
        # makes for its Close button).
        cancel_button = PulseButton(
            on_click_callable=self._handle_cancel,
            text=cancel_text,
            variant="muted",
            compact=True,
        )
        confirm_button = PulseButton(
            on_click_callable=self._handle_confirm,
            text=confirm_text,
            variant="stop" if destructive else "teal",
            compact=True,
        )

        actions: list[ft.Control] = [cancel_button]
        if secondary_text is not None:
            secondary_button = PulseButton(
                on_click_callable=self._handle_secondary,
                text=secondary_text,
                variant="stop" if secondary_destructive else "muted",
                compact=True,
            )
            actions.append(secondary_button)
        actions.append(confirm_button)

        super().__init__(
            title=title,
            body=BodyText(message),
            actions=actions,
            width=420,
        )

    async def _handle_cancel(self) -> None:
        """Close the dialog without firing the confirm callback."""
        self.open = False
        self._page.update()

    async def _handle_confirm(self) -> None:
        """Close the dialog and dispatch the confirm callback."""
        self.open = False
        self._page.update()
        await self._dispatch(self._on_confirm)

    async def _handle_secondary(self) -> None:
        """Close the dialog and dispatch the secondary callback."""
        self.open = False
        self._page.update()
        await self._dispatch(self._on_secondary)

    async def _dispatch(self, callback: AsyncClickCallable | None) -> None:
        if callback is None:
            return
        await callback()

    def show(self) -> None:
        """Show the dialog."""
        self._page.open(self)
