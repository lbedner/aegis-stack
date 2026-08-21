"""Themed switch.

A compact ``ft.Switch`` in brand colors. The stock Material switch is
visually tall next to the dashboard's 40px controls; ``SWITCH_SCALE``
shrinks it, and because every dashboard switch goes through this
control, the knob below retunes all of them at once.
"""

from typing import Any

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme

# Render scale for every dashboard switch (1.0 = stock Material size).
SWITCH_SCALE = 0.5


class ThemedSwitch(ft.Switch):  # type: ignore[misc]
    """Brand-colored, compact switch. Accepts all ``ft.Switch`` kwargs."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("active_color", Theme.Colors.SUCCESS)
        kwargs.setdefault("scale", SWITCH_SCALE)
        super().__init__(**kwargs)
