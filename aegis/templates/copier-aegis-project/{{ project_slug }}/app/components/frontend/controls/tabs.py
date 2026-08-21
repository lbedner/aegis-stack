"""The house tab bar.

``ft.Tabs`` styling was repeated at every call site - label colour,
unselected colour, indicator colour, animation - which is how six tab
groups ended up with a grey indicator and two with a teal one. The
styling belongs to the control, so a new tab group is correct by
default and nobody has to remember the recipe.
"""

import flet as ft

from app.components.frontend.theme import AegisTheme as Theme

# Matches the DateRangeChips / PulseButton selected state: the accent
# marks WHICH ONE, and nothing else in the bar competes with it.
_INDICATOR_COLOR = Theme.Colors.ACCENT
_ANIMATION_MS = 200


class PulseTabs(ft.Tabs):
    """Tab bar with the house treatment: teal indicator, muted labels.

    Takes everything ``ft.Tabs`` takes; the styling arguments are just
    defaulted, so a caller that genuinely needs a different indicator can
    still pass one.
    """

    def __init__(
        self,
        *,
        tabs: list[ft.Tab],
        selected_index: int = 0,
        expand: bool = True,
        **kwargs: object,
    ) -> None:
        kwargs.setdefault("label_color", ft.Colors.ON_SURFACE)
        kwargs.setdefault("unselected_label_color", ft.Colors.ON_SURFACE_VARIANT)
        kwargs.setdefault("indicator_color", _INDICATOR_COLOR)
        kwargs.setdefault("animation_duration", _ANIMATION_MS)
        super().__init__(
            tabs=tabs,
            selected_index=selected_index,
            expand=expand,
            **kwargs,  # type: ignore[arg-type]
        )
