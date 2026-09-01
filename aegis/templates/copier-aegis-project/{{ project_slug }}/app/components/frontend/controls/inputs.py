"""The bare house text input as a control.

``FormTextField`` (form_fields) is a labeled form ROW; this is the
inline field itself - search boxes, composers, toolbars - wearing the
one input recipe with call-site kwargs winning over it.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls.form_fields import (
    FormVariant,
    input_field_kwargs,
)


class StyledTextField(ft.TextField):  # type: ignore[misc]
    """The bare house text input as a control.

    ``FormTextField`` is a labeled form ROW; this is the inline field
    itself - search boxes, composers, toolbars - wearing the one input
    recipe (border, background, focus colors) with call-site kwargs
    winning over the recipe.
    """

    def __init__(
        self,
        *,
        variant: FormVariant = "default",
        error: str | None = None,
        compact: bool = False,
        **kwargs: Any,
    ) -> None:
        merged = input_field_kwargs(variant, error, compact)
        merged.update(kwargs)
        super().__init__(**merged)
