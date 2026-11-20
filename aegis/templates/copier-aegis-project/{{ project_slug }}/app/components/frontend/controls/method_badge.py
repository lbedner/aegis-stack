"""HTTP method colored badge.

Lifted out of ``backend_modal`` so other surfaces (load-test results,
future route-centric tabs) can use the same color scheme.
"""

import flet as ft

from app.components.frontend.theme import SERIES
from app.components.frontend.theme import AegisTheme as Theme

from .text import LabelText

METHOD_COLORS: dict[str, str] = {
    "GET": SERIES[3],
    "POST": SERIES[5],
    "PUT": SERIES[6],
    "PATCH": SERIES[1],
    "DELETE": Theme.Colors.ERROR,
}


class MethodBadge(ft.Container):
    """Colored pill for an HTTP method."""

    def __init__(self, method: str) -> None:
        super().__init__(
            content=LabelText(method, color=ft.Colors.ON_PRIMARY),
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
            bgcolor=METHOD_COLORS.get(method, ft.Colors.ON_SURFACE_VARIANT),
            border_radius=4,
        )
