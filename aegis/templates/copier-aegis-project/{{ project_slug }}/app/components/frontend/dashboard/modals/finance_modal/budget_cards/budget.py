"""What a budget line or a month's outlook shows.

The stat cells both tabs put above their table, the compact row
the lines tab repeats, and the chips and captions that annotate
them.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.table import TableNameText

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
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _MONTH_NAMES,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _budget_status_color,
    _usd,
)
from app.components.frontend.theme import AegisTheme as Theme


def budget_stats_cells(
    stats: dict[str, Any],
) -> list[tuple[str, str, str, str | None]]:
    """(label, value, caption, color) for the Budget header strip.

    Four figures answer the tab's actual question - "do these settings
    clear the month": what comes in, what the bills take, what the
    budgets take, and the signed remainder. The old strip led with
    flexible-spending percentages and an "On track" count; that is
    process, and it lives on the line bars themselves now.

    Colour only for the number in trouble (headline_stat_color's rule):
    a negative month is red, a healthy one wears no accent at all.
    """
    net = stats.get("month_net", 0)
    residual = stats.get("trim_residual", 0)
    if net >= 0:
        verdict = f"+{_usd(net)}"
        verdict_caption = "Left over at these settings"
        # The verdict cell colours in both directions - red when short,
        # accent teal when clear. It's the month's answer, not decoration.
        verdict_color = Theme.Colors.ACCENT
    else:
        verdict = _usd(net)
        verdict_caption = (
            f"Short this month · {stats.get('days_left_in_period', 0)} days left"
        )
        if residual > 0:
            verdict_caption = (
                f"Short this month · {_usd(residual)} of it is bills, not budgets"
            )
        verdict_color = Theme.Colors.ERROR
    return [
        (
            "Income",
            _usd(stats.get("income_total", 0)),
            f"{stats.get('income_count', 0)} confirmed source"
            f"{'s' if stats.get('income_count', 0) != 1 else ''} / month",
            None,
        ),
        (
            "Bills",
            _usd(stats.get("fixed_total", 0)),
            f"{stats.get('fixed_count', 0)} bills / month",
            None,
        ),
        (
            "Budgets",
            _usd(stats.get("flexible_allocated", 0)),
            f"{_usd(stats.get('flexible_spent', 0))} spent so far · "
            f"{stats.get('flexible_count', 0)} limits"
            + (
                # Goals ride this cell as a caption, not a fifth cell -
                # the strip is already width-tight at four.
                f" · + {_usd(goals_total)} to goals"
                if (goals_total := stats.get("goals_total", 0)) > 0
                else ""
            ),
            None,
        ),
        # The sixth term earns a CELL, not a caption: when discovered it
        # was bigger than the budgets figure, and the verdict is a lie
        # without it. Absent entirely at zero - a fresh install keeps
        # the four-cell strip.
        *(
            [
                (
                    "Everything else",
                    _usd(everything_else),
                    "observed · not in bills or limits",
                    None,
                )
            ]
            if (everything_else := stats.get("everything_else", 0)) > 0
            else []
        ),
        ("This month", verdict, verdict_caption, verdict_color),
    ]


def outlook_month_label(period_month: int) -> str:
    """YYYYMM -> "October 2026"."""
    return f"{_MONTH_NAMES[period_month % 100 - 1]} {period_month // 100}"


def outlook_stats_cells(
    entry: dict[str, Any],
) -> list[tuple[str, str, str, str | None]]:
    """The header's four cells for a FUTURE month: same shape, but bills
    at face value on their real cadence - the month the annual premium
    lands looks like that month. The verdict cell is titled with the
    month itself, so a paged header can never be mistaken for today's."""
    net = entry.get("month_net", 0)
    goals = entry.get("goals", 0)
    envelopes = entry.get("envelopes", 0)
    budgets_caption = "standing limits"
    extras = []
    if goals > 0:
        extras.append(f"+ {_usd(goals)} to goals")
    if envelopes > 0:
        extras.append(f"+ {_usd(envelopes)} to envelopes")
    if extras:
        budgets_caption += " · " + " · ".join(extras)
    return [
        ("Income", _usd(entry.get("income_due", 0)), "due that month", None),
        (
            "Bills",
            _usd(entry.get("bills_due", 0)),
            "landing that month, face value",
            None,
        ),
        ("Budgets", _usd(entry.get("budgets", 0)), budgets_caption, None),
        *(
            [
                (
                    "Everything else",
                    _usd(everything_else),
                    "observed · not in bills or limits",
                    None,
                )
            ]
            if (everything_else := entry.get("everything_else", 0)) > 0
            else []
        ),
        (
            outlook_month_label(entry.get("period_month", 0)),
            f"+{_usd(net)}" if net >= 0 else _usd(net),
            f"at these settings · ends around {_usd(entry.get('end_balance', 0))}",
            Theme.Colors.ACCENT if net >= 0 else Theme.Colors.ERROR,
        ),
    ]


def outlook_chip(entry: dict[str, Any]) -> tuple[str, str]:
    """(label, color) for one month's chip: the projected cash it ENDS
    with ("Oct $1,240"), compounded from today's real balance - the
    LEVEL, not the rate. Red means literally out of money that month,
    which is the only red a bank balance understands."""
    balance = entry.get("end_balance", 0)
    month = _MONTH_NAMES[entry.get("period_month", 0) % 100 - 1][:3]
    dollars = round(balance / 100)
    label = f"{month} {'-' if balance < 0 else ''}${abs(dollars):,}"
    return label, Theme.Colors.ERROR if balance < 0 else Theme.Colors.TEXT_SECONDARY


def budget_lines_grid(rows: list[ft.Control]) -> ft.ResponsiveRow:
    """Budget lines as a flowing grid, three per row when there is room.

    Full-width stacking gave a dozen lines a page of scrolling for no
    information - each line is a label, a small bar and two numbers.
    12-grid columns: 4 on a large window (three per row), 6 on a middling
    one (two), 12 when cramped - the narrow case degrades to exactly the
    old one-per-row layout rather than crushing the bars.
    """
    return ft.ResponsiveRow(
        [ft.Container(content=row, col={"sm": 12, "md": 6, "lg": 4}) for row in rows],
        spacing=Theme.Spacing.MD,
        run_spacing=Theme.Spacing.SM,
    )


def compact_budget_row(
    label: str, allocated: int, spent: int, status: str
) -> ft.Control:
    """One flexible budget line, on the trim rows' geometry.

    The previous row stacked label / 8px bar / a 16px-bold percent line -
    three storeys per limit, so a dozen limits filled the screen while
    "Close the gap" fit twelve rows in four lines. Same shape as a trim
    row now: name over the figures on the left, one right-aligned percent,
    and the bar slimmed to a 4px strip between them.

    The bar clamps at 100% (Flet's ``ProgressBar`` has no over-100
    concept) but the PERCENT never lies: an overrun reads "129%", in
    error red. Monochrome-first everywhere else - a healthy line's
    percent carries no accent at all.
    """
    color = _budget_status_color(status)
    pct = (spent / allocated * 100) if allocated > 0 else (100.0 if spent > 0 else 0.0)
    pct_color = (
        Theme.Colors.ERROR
        if status == "critical"
        else Theme.Colors.WARNING
        if status == "warn"
        else Theme.Colors.TEXT_SECONDARY
    )
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Container(content=TableNameText(label), expand=True),
                    NumericText(
                        f"{pct:.0f}%",
                        size=Theme.Typography.BODY_SMALL,
                        color=pct_color,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.ProgressBar(
                value=min(pct, 100.0) / 100.0,
                height=4,
                color=color,
                bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE),
                border_radius=2,
            ),
            SecondaryText(
                f"{_usd(spent)} of {_usd(allocated)}",
                size=Theme.Typography.BODY_SMALL,
            ),
        ],
        spacing=Theme.Spacing.XS,
        tight=True,
    )


def budget_suggestion_caption(pick: dict[str, Any]) -> str:
    """The evidence line under a budget suggestion.

    Says the thing the gate actually measured: how many of the six months
    had spend, and how many of those did not look like the others. The
    row used to print an "Nx swing", which stopped meaning anything when
    the steadiness test changed - it read a field that no longer existed
    and rendered "0.0x swing" on every suggestion, a default wearing the
    clothes of a measurement.

    An absent count says nothing rather than zero, for the same reason.
    """
    caption = f"{pick.get('months_seen', 0)} of 6 months"
    unusual = pick.get("unusual_months")
    if unusual is None:
        return caption
    if unusual == 0:
        return f"{caption}  ·  every month alike"
    plural = "s" if unusual != 1 else ""
    return f"{caption}  ·  {unusual} month{plural} stood out"
