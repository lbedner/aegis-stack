"""Generic bordered dropdown: an inline trigger, panel floats via page.overlay.

Flet's native popup/menu surfaces can't give us a bordered panel here.
``PopupMenuTheme.shape`` only accepts a ``RoundedRectangleBorder``, which
carries a corner radius and nothing else - no ``side`` - so a
``PopupMenuButton`` popup can never draw a stroke. ``MenuBar`` +
``SubmenuButton`` do expose a ``MenuStyle.side``, but that widget pair
crashes ("Null check operator used on a null value") in this Flet build
even with a minimal, standards-conformant tree.

A first version tried nesting trigger + panel in one local ``ft.Stack``
with ``clip_behavior=NONE`` so the panel could overflow its box. That
solved the border but not visibility: painting is still governed by
tree order, so anything painted *after* the trigger in the surrounding
layout (cards below it, in this app's case) painted over the floating
panel regardless of the overflow.

This version uses the same fix the app already relies on for exactly
this class of problem: ``page.overlay`` (see ``BasePopup`` and the file
picker in ``finance_modal.py``). Overlay entries paint above ordinary
page content in append order - which is how the Finance modal itself
gets drawn above the dashboard - so a panel appended after the modal is
already open paints on top of it, dependably, regardless of where the
trigger sits in the layout. Position comes from the trigger's own
``on_tap_down`` event: Flet's ``ContainerTapEvent`` carries both
``local_x/y`` (tap position within the trigger) and ``global_x/y`` (tap
position on the page), so ``global - local`` is the trigger's exact
page-absolute top-left corner - not a guess. The one thing Flet still
can't hand back is the trigger's rendered width/height, so those stay
caller-tunable estimates (``trigger_width``/``trigger_height``).

An earlier version sized the panel as a fraction of ``page.width`` /
``page.height``. That broke as soon as the browser's zoom level at
session start was anything other than 100%: the panel showed up nowhere
near the trigger, off past the left edge of the screen. ``page.width``
and the tap event's ``global_x``/``local_x`` turn out not to live in the
same coordinate space once zoom is involved - mixing the two in one
formula (``page.width - trigger_left``) produces nonsense proportional
to however far off 100% the zoom was. The fix is to never mix them:
every dimension here - position *and* size - comes only from the
trigger's own tap coordinates and its own estimated box
(``trigger_width``/``trigger_height``), never from page dimensions.
That is also a more literal reading of "proportional to whatever is
calling it" than a page-fraction ever was.

Click-outside-to-dismiss comes for free from the same transparent,
page-filling backdrop ``BasePopup`` uses.

This control is built once and mounted once per session in this app's
own modals (detail dialogs are cached and shown/hidden, not recreated
per open - see ``_open_modal`` in ``card_utils.py``), so ``did_mount``
appends to ``page.overlay`` exactly once, guarded the same way the file
picker's comment describes. A caller whose control tree is genuinely
rebuilt on every open would need its own teardown; that isn't this
app's pattern today.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme

# Flet has no live "measure this widget" API, so the trigger's box has
# to be estimated rather than read back - these match a compact
# chip-style trigger (icon + short label). Override per instance for a
# differently sized trigger.
_DEFAULT_TRIGGER_WIDTH = 160
_DEFAULT_TRIGGER_HEIGHT = 32


class Dropdown(ft.Container):
    """An inline trigger that opens a bordered panel anchored beneath it.

    ``trigger`` is whatever should be clickable (icon + text row, a
    button, ...); ``panel`` is the (typically scrollable) content shown
    inside the bordered frame. Swap either later via ``set_trigger`` /
    ``set_panel`` - useful when a caller rebuilds its label or rows in
    response to state changes without needing a whole new ``Dropdown``.
    """

    def __init__(
        self,
        trigger: ft.Control,
        panel: ft.Control | None = None,
        *,
        align: str = "right",
        anchor_gap: int = 6,
        trigger_width: int = _DEFAULT_TRIGGER_WIDTH,
        trigger_height: int = _DEFAULT_TRIGGER_HEIGHT,
        width_multiplier: float = 2.2,
        min_width: int = 240,
        max_width: int = 420,
        max_height: int | None = 480,
        trigger_padding: ft.Padding | None = None,
    ) -> None:
        if align not in ("left", "right"):
            raise ValueError("align must be 'left' or 'right'")
        self._align = align
        self._anchor_gap = anchor_gap
        self._trigger_width = trigger_width
        self._trigger_height = trigger_height
        self._width_multiplier = width_multiplier
        self._min_width = min_width
        self._max_width = max_width
        self._max_height = max_height
        self._is_open = False
        self._mounted_overlay = False

        self._trigger_box = ft.Container(
            content=trigger,
            on_tap_down=self._toggle,
            ink=True,
            border_radius=Theme.Components.BUTTON_RADIUS,
            # A bare trigger (icon + label) needs this padding to become a
            # tap target; one that already carries its own chrome (a
            # bordered pill) must pass ``ft.padding.all(0)`` instead, or
            # the frame's padding inflates the pill's own box.
            padding=(
                ft.padding.symmetric(
                    vertical=Theme.Spacing.XS, horizontal=Theme.Spacing.SM
                )
                if trigger_padding is None
                else trigger_padding
            ),
        )
        super().__init__(content=self._trigger_box)

        # Same border/shadow recipe as StyledAlertDialog's panel - a plain
        # Container carries the stroke, since no native shape here can.
        self._panel_frame = ft.Container(
            content=panel,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            # A Container never clips its own content by default - a
            # panel whose content is taller than its box (a long,
            # unfiltered category list, confirmed live: it kept painting
            # straight past the rounded border, over everything below)
            # just overflows past the border/shadow instead of scrolling
            # inside it. HARD_EDGE is the same fix StyledAlertDialog's own
            # panel already needed for the same reason.
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
            padding=ft.padding.symmetric(vertical=Theme.Spacing.SM),
            on_click=lambda e: None,  # stop taps inside the panel closing it
        )
        # Full-page, invisible click-catcher - closes the panel on any
        # tap outside it. Same technique as BasePopup's backdrop, just
        # transparent: a small filter menu shouldn't dim the whole app.
        backdrop = ft.Container(
            bgcolor=ft.Colors.TRANSPARENT,
            expand=True,
            on_click=self._close,
        )
        self._overlay_layer = ft.Stack(
            controls=[backdrop, self._panel_frame],
            expand=True,
            visible=False,
        )

    def did_mount(self) -> None:
        if self._mounted_overlay or self.page is None:
            return
        self._mounted_overlay = True
        self.page.overlay.append(self._overlay_layer)
        # Appending alone doesn't register the control with Flet's runtime
        # (no internal page reference until an update flushes it) - unlike
        # the file picker elsewhere in this app, nothing else is guaranteed
        # to call page.update() before this control's first open.
        self.page.update()

    def will_unmount(self) -> None:
        # A Dropdown built fresh per dialog open (CategoryPickerField)
        # would otherwise strand one overlay layer per open forever -
        # ``page.overlay`` never forgets on its own. Resetting the flag
        # lets a remount re-append cleanly.
        if self._mounted_overlay and self.page is not None:
            if self._overlay_layer in self.page.overlay:
                self.page.overlay.remove(self._overlay_layer)
            self._mounted_overlay = False

    def set_trigger(self, trigger: ft.Control) -> None:
        self._trigger_box.content = trigger
        if self.page is not None:
            self._trigger_box.update()

    def set_panel(self, panel: ft.Control) -> None:
        self._panel_frame.content = panel
        # ``_panel_frame`` lives inside ``_overlay_layer``, only actually
        # attached to the page in ``did_mount`` (page.overlay.append) -
        # ``self.page is not None`` alone isn't enough here the way it is
        # for _trigger_box (a normal child, mounted with ``self``): this
        # Dropdown can already have a page reference from its own parent
        # while ``did_mount`` hasn't run yet, and a caller whose own
        # did_mount races ahead of this one (e.g. UncategorizedPanel's
        # AccountFilterButton, freshly built inside a just-opened dialog -
        # confirmed live: "Container Control must be added to the page
        # first") would call this before ``_panel_frame`` is really on the
        # page. Content assigned before the real mount still shows
        # correctly once it happens - did_mount's own page.update() paints
        # it - so skipping this update() in that window is a no-op, not a
        # missed render.
        #
        # Ask ``_panel_frame`` itself rather than ``_mounted_overlay``:
        # ``did_mount`` sets that flag one line BEFORE the append, so it is
        # a promise, not a fact, and a caller landing in that window still
        # hit "Container Control must be added to the page first".
        if self._panel_frame.page is not None:
            self._panel_frame.update()

    def close(self) -> None:
        self._set_open(False)

    def _close(self, _e: ft.ControlEvent) -> None:
        self._set_open(False)

    def _toggle(self, e: ft.ContainerTapEvent) -> None:
        if self._is_open:
            self._set_open(False)
            return
        # Everything below derives only from this one event's own
        # coordinates and the trigger's own estimated box - never from
        # page.width/page.height, which don't share a coordinate space
        # with tap events once the browser isn't at 100% zoom (see the
        # module docstring).
        trigger_left = e.global_x - e.local_x
        trigger_top = e.global_y - e.local_y

        width = max(
            self._min_width,
            min(self._max_width, int(self._trigger_width * self._width_multiplier)),
        )
        self._panel_frame.width = width
        # ``None`` = hug the content: a fixed height is right for a long
        # scrolling list (it caps the panel and lets the list scroll
        # inside), but it would strand a short, fixed menu of two or
        # three actions inside a half-empty box.
        self._panel_frame.height = self._max_height
        self._panel_frame.top = trigger_top + self._trigger_height + self._anchor_gap
        if self._align == "right":
            # Right edge of the panel meets the right edge of the trigger.
            left = trigger_left + self._trigger_width - width
        else:
            left = trigger_left
        # A trigger near the screen's left edge pushes a right-aligned
        # panel to negative x (confirmed live: the strip's leftmost cell
        # opened its popup half off-screen). Clamping needs no page
        # dimensions - it only ever moves the panel right - so it is
        # safe in this coordinate space at any zoom.
        self._panel_frame.left = max(float(Theme.Spacing.MD), left)
        self._panel_frame.right = None
        self._set_open(True)

    def _set_open(self, open_: bool) -> None:
        self._is_open = open_
        self._overlay_layer.visible = open_
        if self.page is not None:
            self._overlay_layer.update()


class NativeDropdown(ft.Dropdown):  # type: ignore[misc]
    """A themed NATIVE ft.Dropdown, for use INSIDE real dialogs.

    The overlay ``Dropdown`` above (and every picker built on it) paints via
    ``page.overlay``, which renders BEHIND an ``ft.AlertDialog`` - the exact
    layering problem ``OverlayStyledDialog`` exists for. Inside a dialog the
    native Flutter menu is the only surface that paints on top, so this class
    carries the app's input theming onto ``ft.Dropdown`` instead: one recipe,
    not a copy of nine style kwargs at every dialog call site.

    ``enable_filter``/``enable_search`` default on - a native dropdown is
    only reached for when the option list is too long to scan.
    """

    def __init__(self, **kwargs: Any) -> None:
        from app.components.frontend.theme import AegisTheme as Theme

        defaults: dict[str, Any] = {
            "enable_filter": True,
            "enable_search": True,
            "dense": True,
            "width": 300,
            "border_radius": Theme.Components.INPUT_RADIUS,
            "bgcolor": ft.Colors.SURFACE,
            "border_color": ft.Colors.OUTLINE,
            "focused_border_color": Theme.Colors.PRIMARY,
            "text_size": 13,
            "content_padding": ft.padding.symmetric(horizontal=12, vertical=6),
            "menu_height": 240,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)
