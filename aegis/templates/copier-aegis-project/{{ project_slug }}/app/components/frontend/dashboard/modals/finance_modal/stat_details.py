"""
Finance Service Detail Modal

A Quicken-style finance workspace, organised into tabs:

* **Accounts** — the register. A left sidebar lists accounts grouped into
  Banking / Credit / Investments / etc., each with its balance and a grand
  total; selecting one shows an account-detail header (with a Manage menu)
  above its transactions (or holdings, for investment accounts). The sidebar
  only lives on this tab.
* **Overview** — a net-worth summary (assets, liabilities, net worth) with a
  per-group breakdown. No sidebar; this is the "home" landing.

Data is fetched async through the internal ``APIClient`` (never a DB session
from the frontend). All colours, spacing, and type come from ``AegisTheme``.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.dropdown import Dropdown

# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
# One height for every Overview card, so the row has a single baseline.
# Named slices in the spending donut (and rows in the list under it) before
# the tail folds into "Other". Five left "Other" as the biggest slice on any
# real ledger, which hides exactly the breakdown the card exists to show.
# Measured against a real ledger (23 parent-level categories after the
# spending_by_category rollup): 10 slices still left "Other" at 16.3%; 15
# gets it to 5.3%, with everything past #15 individually under 1% of total
# spend - the tail at that point really is "everything else", not a few
# disguised top categories. PieChartCard's legend scrolls within its fixed
# height (modal_sections.py) rather than clipping, so this isn't bounded
# by legend space anymore.
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.theme import AegisTheme as Theme


def equation_rows(stats: dict[str, Any]) -> list[dict[str, Any]]:
    """The month verdict as its own arithmetic, line by line - built from
    the SAME stats dict the strip renders, so the popup and the cells can
    never disagree. Zero terms stay out (a fresh install's equation is
    three lines, not six)."""
    rows: list[dict[str, Any]] = [
        {"label": "Income", "value": stats.get("income_total", 0), "caption": None},
        {"label": "Bills", "value": -stats.get("fixed_total", 0), "caption": None},
        {
            "label": "Budgets",
            "value": -stats.get("flexible_allocated", 0),
            "caption": None,
        },
    ]
    for label, key in (
        ("Goals", "goals_total"),
        ("Envelopes", "envelopes_total"),
        ("Everything else", "everything_else"),
    ):
        if stats.get(key, 0):
            rows.append({"label": label, "value": -stats[key], "caption": None})
    rows.append(
        {"label": "This month", "value": stats.get("month_net", 0), "caption": None}
    )
    return rows


def stat_detail_panel(
    title: str, rows: list[dict[str, Any]], *, footer: str | None = None
) -> ft.Column:
    """The body of a header cell's click-through popup: dense label/value
    rows (money right-aligned), an optional muted footer naming the
    window. One builder for all five cells - they differ only in rows."""
    children: list[ft.Control] = [
        SecondaryText(title.upper(), size=Theme.Typography.CAPTION),
    ]
    for row in rows:
        value = int(row.get("value", 0))
        amount = _usd(abs(value)) if value >= 0 else f"-{_usd(-value)}"
        label_bits: list[ft.Control] = [
            ft.Container(
                content=SecondaryText(
                    str(row.get("label", "")),
                    size=Theme.Typography.BODY_SMALL,
                    color=ft.Colors.ON_SURFACE,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                expand=True,
            ),
        ]
        caption = row.get("caption")
        if caption:
            label_bits.append(
                SecondaryText(str(caption), size=Theme.Typography.CAPTION)
            )
        label_bits.append(
            NumericText(
                amount,
                size=Theme.Typography.BODY_SMALL,
                color=Theme.Colors.ERROR if value < 0 else ft.Colors.ON_SURFACE,
            )
        )
        children.append(
            ft.Row(
                label_bits,
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
    if footer:
        children.append(SecondaryText(footer, size=Theme.Typography.CAPTION))
    return ft.Column(
        children,
        spacing=Theme.Spacing.XS,
        tight=True,
        scroll=ft.ScrollMode.AUTO,
    )


class StatDetailPopup(Dropdown):
    """One anchored popup for every header cell - the "locked" hover the
    strip needed: click a cell, the panel opens at the tap and stays
    until a click elsewhere dismisses it (the account filter's own
    mechanics, reused). No visible trigger; every open comes through
    ``open_at`` positioned at the caller's event."""

    def __init__(self) -> None:
        self._slot = ft.Container()
        super().__init__(
            trigger=ft.Container(width=0, height=0),
            panel=self._slot,
            trigger_width=200,
            min_width=300,
            max_width=340,
            max_height=380,
        )

    def open_at(
        self,
        e: ft.ControlEvent,
        title: str,
        rows: list[dict[str, Any]],
        *,
        footer: str | None = None,
    ) -> None:
        self._slot.content = stat_detail_panel(title, rows, footer=footer)
        self.close()
        self._toggle(e)  # type: ignore[arg-type]


def stat_detail_caption(row: dict[str, Any]) -> str | None:
    """Caption for one stat-detail row - the copy lives with the surface.

    The service ships data only: a sub-monthly bill carries its cadence
    and face value, an everything-else row carries its transaction count.
    """
    count = row.get("transaction_count")
    if count is not None:
        return f"{count} row{'s' if count != 1 else ''}"
    frequency = row.get("frequency")
    if not frequency:
        return None
    per_period = row.get("per_period_amount")
    if per_period is not None:
        return f"${per_period / 100:,.2f} {frequency}"
    return frequency


def _captioned(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**row, "caption": stat_detail_caption(row)} for row in rows]


def stat_window_label(details: dict[str, Any]) -> str:
    """ "May - Jul 2026 average" from the [start, end) window bounds."""
    from datetime import date as date_cls

    try:
        start = date_cls.fromisoformat(str(details.get("window_start")))
        end = date_cls.fromisoformat(str(details.get("window_end")))
    except (TypeError, ValueError):
        return ""
    last_year, last_month = end.year, end.month - 1
    if last_month == 0:
        last_year, last_month = last_year - 1, 12
    last = date_cls(last_year, last_month, 1)
    return f"{start.strftime('%b')} - {last.strftime('%b %Y')} average"
