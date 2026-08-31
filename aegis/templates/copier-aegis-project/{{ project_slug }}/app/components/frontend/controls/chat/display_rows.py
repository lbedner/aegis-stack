"""One card detail row: label, value, and teal on what changes.

Shared by the single pending-change card and the batch card so the two
render one visual language: the subject line is context, every later
row is a proposed fact, and teal lands on exactly the changing part -
an arrow's target, or the leading amount of a "$3.99 · memo" line.
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

_ARROW = " \u2192 "


def _value_text(value: str, *, color: str, **kwargs: Any) -> SecondaryText:
    """A display value; a "before \u2192 after" line gets its target in
    accent teal so the eye lands on what will change."""
    if _ARROW not in value:
        return SecondaryText(value, color=color, **kwargs)
    before, _, target = value.rpartition(_ARROW)
    return SecondaryText(
        "",
        color=color,
        spans=[
            ft.TextSpan(before + _ARROW),
            ft.TextSpan(target, style=ft.TextStyle(color=Theme.Colors.ACCENT)),
        ],
        **kwargs,
    )


def _detail_value_text(value: str, *, dimmed: bool, **kwargs: Any) -> SecondaryText:
    """One detail row's value, teal on exactly what is changing: an
    arrow's TARGET, or the leading amount of a "$3.99 · memo" line (the
    memo is prose and stays neutral - a wall of teal marks nothing). A
    dimmed row (rejected/vetoed) never highlights - teal means "will
    happen"."""
    if dimmed:
        return SecondaryText(value, color=ft.Colors.OUTLINE, **kwargs)
    if _ARROW in value:
        return _value_text(value, color=ft.Colors.ON_SURFACE, **kwargs)
    head, sep, tail = value.partition(" · ")
    if not sep:
        return SecondaryText(value, color=Theme.Colors.ACCENT, **kwargs)
    return SecondaryText(
        "",
        color=ft.Colors.ON_SURFACE,
        spans=[
            ft.TextSpan(head, style=ft.TextStyle(color=Theme.Colors.ACCENT)),
            ft.TextSpan(sep + tail),
        ],
        **kwargs,
    )


def _display_rows(
    display: list[dict[str, Any]], *, dimmed: bool
) -> list[ft.Control]:
    """A card's detail rows: the subject (payee/amount/date, always
    display[0] by every executor's own convention) renders as context,
    never highlighted; every row after it is a proposed fact and gets
    ``_detail_value_text``'s highlighting. One label, one line - never
    flattened into a single dot-joined string."""
    if not display:
        return []
    subject_color = ft.Colors.OUTLINE if dimmed else ft.Colors.ON_SURFACE
    rows: list[ft.Control] = [
        SecondaryText(str(display[0].get("value", "")), color=subject_color)
    ]
    for line in display[1:]:
        # Only DIMMED rows pin OUTLINE (a border color, barely visible
        # by design); a live label needs SecondaryText's own
        # theme-aware secondary color, not that.
        label_kwargs: dict[str, Any] = {"size": Theme.Typography.BODY_SMALL}
        if dimmed:
            label_kwargs["color"] = ft.Colors.OUTLINE
        rows.append(
            ft.Row(
                [
                    SecondaryText(str(line.get("label", "")), **label_kwargs),
                    ft.Container(
                        content=_detail_value_text(
                            str(line.get("value", "")),
                            dimmed=dimmed,
                            text_align=ft.TextAlign.RIGHT,
                        ),
                        expand=True,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        )
    return rows
