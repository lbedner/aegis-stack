"""
Custom text controls with proper theme-aware styling.

These components automatically use semantic Flet colors that adapt to light/dark themes,
following the Aegis Stack design system for consistent visual design.
"""

from typing import Any

import flet as ft

from ..styles import FontConfig
from ..theme import AegisTheme as Theme
from ..theme import DarkColorPalette


class NumericText(ft.Text):  # type: ignore[misc]
    """Text for figures: money, counts, percentages, axis ticks.

    Uses the tabular face from ``FontConfig.FAMILY_NUMERIC`` so every digit
    takes the same width. In a proportional face a right-aligned column of
    amounts shifts sideways as the digits change, which is the thing that
    makes a table of money feel subtly unsettled.

    Takes the same keyword arguments as ``ft.Text``; pass ``size``, ``weight``,
    and ``color`` to match whatever it sits beside.
    """

    def __init__(self, value: str, **kwargs: Any) -> None:
        defaults = {
            "font_family": FontConfig.FAMILY_NUMERIC,
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_REGULAR,
            "color": DarkColorPalette.TEXT_PRIMARY_DEFAULT,
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, **defaults)


class PrimaryText(ft.Text):  # type: ignore[misc]
    """
    Primary text component using theme-aware text colors.

    Automatically adapts to light/dark themes with proper contrast.
    Use for main content text, labels, and primary information.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "no_wrap": False,
            "font_family": "Roboto",
            "size": Theme.Typography.BODY_LARGE,
            "weight": Theme.Typography.WEIGHT_REGULAR,
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class SecondaryText(ft.Text):  # type: ignore[misc]
    """
    Secondary text component using theme-aware secondary text colors.

    Automatically adapts to light/dark themes with reduced contrast.
    Use for supporting text, captions, and less prominent information.
    """

    def __init__(
        self, value: str, opacity: float = 1.0, no_wrap: bool = False, **kwargs: Any
    ) -> None:
        defaults = {
            "no_wrap": no_wrap,
            "font_family": "Roboto",
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_REGULAR,
            "color": DarkColorPalette.TEXT_SECONDARY_DEFAULT,
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class TitleText(ft.Text):  # type: ignore[misc]
    """
    Title text component for headings and prominent labels.

    Uses theme-aware colors with larger size and bold weight.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        # Set defaults, but allow kwargs to override
        defaults = {
            "font_family": "Roboto",
            "size": Theme.Typography.H2,
            "weight": Theme.Typography.WEIGHT_BOLD,
            "selectable": False,
        }
        # Update defaults with any provided kwargs
        defaults.update(kwargs)

        super().__init__(
            value=value,
            opacity=opacity,
            **defaults,
        )


class ConfirmationText(ft.Text):  # type: ignore[misc]
    """
    Confirmation/error text component with error coloring.

    Uses theme-aware error colors for warnings, confirmations, and alerts.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "color": Theme.Colors.ERROR,
            "font_family": "Roboto",
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_REGULAR,
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class MetricText(NumericText):  # type: ignore[misc]
    """
    Specialized text for displaying metrics and numerical values.

    ``NumericText`` at emphasis weight: the tabular figures come from the
    parent, this only sets the size and weight a headline number wants.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY_LARGE,
            "weight": Theme.Typography.WEIGHT_BOLD,
        }
        defaults.update(kwargs)
        super().__init__(value, opacity=opacity, **defaults)


class LabelText(ft.Text):  # type: ignore[misc]
    """
    Label text component for form labels and small descriptive text.

    Uses smaller size with medium weight for clear labeling.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        # Set defaults, but allow kwargs to override
        defaults = {
            "font_family": "Roboto",
            "size": Theme.Typography.BODY_SMALL,
            "weight": Theme.Typography.WEIGHT_SEMIBOLD,
            "selectable": False,
        }
        # Update defaults with any provided kwargs
        defaults.update(kwargs)

        super().__init__(
            value=value,
            opacity=opacity,
            **defaults,
        )


# ============================================================================
# NEW THEME-BASED CONTROLS
# ============================================================================


class DisplayText(ft.Text):  # type: ignore[misc]
    """
    Hero display text - largest emphasis.

    Used for major headings, hero sections, and key visual elements.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.DISPLAY,
            "weight": Theme.Typography.WEIGHT_BOLD,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class H1Text(ft.Text):  # type: ignore[misc]
    """
    H1 heading text for page titles.

    Primary heading level for major page sections.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.H1,
            "weight": Theme.Typography.WEIGHT_BOLD,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class H2Text(ft.Text):  # type: ignore[misc]
    """
    H2 heading text for major section headers.

    Secondary heading level for important content sections.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.H2,
            "weight": Theme.Typography.WEIGHT_BOLD,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class H3Text(ft.Text):  # type: ignore[misc]
    """
    H3 heading text for subsection headers.

    Tertiary heading level for subsections and groupings.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.H3,
            "weight": Theme.Typography.WEIGHT_SEMIBOLD,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class BodyText(ft.Text):  # type: ignore[misc]
    """
    Standard body text for general content.

    Default text size for most content areas.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_REGULAR,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class AccentText(ft.Text):  # type: ignore[misc]
    """
    Accent-colored text for emphasis and highlights.

    Uses vibrant accent color for calls-to-action and important highlights.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_MEDIUM,
            "color": Theme.Colors.ACCENT,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class SuccessText(ft.Text):  # type: ignore[misc]
    """
    Success-colored text for positive feedback.

    Uses success color for confirmations and positive states.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_MEDIUM,
            "color": Theme.Colors.SUCCESS,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class WarningText(ft.Text):  # type: ignore[misc]
    """
    Warning-colored text for caution messages.

    Uses warning color for important notices and cautions.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_MEDIUM,
            "color": Theme.Colors.WARNING,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class ErrorText(ft.Text):  # type: ignore[misc]
    """
    Error-colored text for error messages and critical feedback.

    Uses error color for failures and critical issues.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_MEDIUM,
            "color": Theme.Colors.ERROR,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


# ============================================================================
# SPECIALIZED COMPONENT TEXT
# ============================================================================


class ModalText(ft.Text):  # type: ignore[misc]
    """
    Modal title text with bold emphasis.

    Used for dialog and modal headers.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY_LARGE,
            "weight": Theme.Typography.WEIGHT_BOLD,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class ModalSubtitleText(ft.Text):  # type: ignore[misc]
    """
    Modal subtitle text for supporting information.

    Used for dialog descriptions and secondary modal content.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_REGULAR,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class SidebarLabelText(ft.Text):  # type: ignore[misc]
    """
    Sidebar label text with ellipsis overflow.

    Used for navigation items and sidebar content labels.
    """

    def __init__(
        self,
        value: str,
        opacity: float = 1.0,
        width: int = 200,
        **kwargs: Any,
    ) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_REGULAR,
            "font_family": "Roboto",
            "overflow": ft.TextOverflow.ELLIPSIS,
            "width": width,
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)


class SidebarLabelHeadingText(ft.Text):  # type: ignore[misc]
    """
    Sidebar heading text for section headers.

    Used for sidebar section titles and category headers.
    """

    def __init__(self, value: str, opacity: float = 1.0, **kwargs: Any) -> None:
        defaults = {
            "size": Theme.Typography.BODY,
            "weight": Theme.Typography.WEIGHT_BOLD,
            "font_family": "Roboto",
            "selectable": False,
        }
        defaults.update(kwargs)
        super().__init__(value=value, opacity=opacity, **defaults)
