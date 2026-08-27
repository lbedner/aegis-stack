"""The One-time group of the Budget card: deliberate plans, face value on
a date.

A one-off stream is an entry the user typed in on purpose - a dentist
visit, a gift - not detector noise. It has no monthly share, so it lives
outside the Fixed/Non-monthly "/mo" sections, but hiding it entirely hid
plans the user made deliberately. Module-level functions, not mixin
methods: the group reads straight from its bucket and touches no panel
state.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    NumericText,
    SecondaryText,
    SectionCard,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal.budget_cards import (
    budget_lines_grid,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.theme import AegisTheme as Theme


def one_time_section(bucket: dict[str, Any] | None) -> ft.Control | None:
    """Face value and a date, never a "/mo": amortizing a one-off is
    exactly the mistake the monthly buckets exist to avoid. Absent
    entirely when empty - an empty prompt would nag about a kind of
    entry most months don't have."""
    lines = (bucket or {}).get("lines", [])
    if not lines:
        return None
    total = (bucket or {}).get("total_allocated", 0)
    header = ft.Row(
        [
            H3Text("One-time"),
            SecondaryText("Planned once, on a date - not part of the monthly math"),
        ],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return SectionCard(
        title=header,
        body=budget_lines_grid([_one_time_row(line) for line in lines]),
        actions=[SecondaryText(f"Planned - {_usd(total)}")],
        body_padding=Theme.Spacing.MD,
    )


def _one_time_row(line: dict[str, Any]) -> ft.Control:
    label = line.get("payee_label") or line.get("category_name") or "Uncategorized"
    due = line.get("due_date")
    when = date.fromisoformat(due) if due else None
    return ft.Row(
        [
            TableNameText(label),
            ft.Container(expand=True),
            NumericText(_usd(line.get("allocated_amount", 0)), size=14),
            SecondaryText(f"{when.strftime('%b')} {when.day}" if when else "No date"),
        ],
        spacing=Theme.Spacing.MD,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
