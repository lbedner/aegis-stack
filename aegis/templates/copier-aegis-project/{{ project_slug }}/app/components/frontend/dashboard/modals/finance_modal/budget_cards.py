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

from collections.abc import Awaitable, Callable
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ActionMenu,
    ActionMenuItem,
    NumericText,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.buttons import PulseButton
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
from app.core.formatting import format_date


def goal_amounts_line(goal: dict[str, Any]) -> str:
    """ "$1,200.00 of $3,000.00" - saved against the dream's number."""
    return f"{_usd(goal.get('balance', 0))} of {_usd(goal.get('target_amount', 0))}"


def goal_eta_caption(goal: dict[str, Any]) -> str:
    """The card's one-line verdict. Reached/Paused speak for themselves;
    an active goal shows its monthly ask and where that rate lands -
    "at this rate: never" spelled out, exactly as the API's null ETA
    means it ('s contract: nobody downstream recomputes the math).
    """
    if goal.get("status") == "reached" or (goal.get("progress") or 0) >= 1:
        return "Reached"
    if goal.get("status") == "paused":
        return "Paused"
    monthly = f"{_usd(goal.get('monthly_need', 0))}/mo"
    kind = goal.get("contribution_kind", "fixed")
    if kind == "percent_income":
        pct = (goal.get("contribution_pct_bps") or 0) / 100
        pct_text = f"{pct:g}"
        monthly = f"{monthly} ({pct_text}% of income)"
    elif kind == "surplus":
        monthly = f"{monthly} (surplus)"
    eta = goal.get("eta")
    if not eta:
        return f"{monthly} · at this rate: never"
    return f"{monthly} · lands {format_date(eta)}"


def contribution_preview(kind: str, raw_value: str, *, income_total: int) -> str:
    """The dialog's live one-liner naming the BASE a rule evaluates
    against - "10% of $8,200.00/mo = $820.00/mo". The support question a
    percent rule generates is always "10% of WHAT", so the answer is on
    screen before saving. Empty for fixed (the field already IS the
    answer)."""
    if kind == "surplus":
        return (
            "Sweeps whatever the month has left after bills, budgets, and higher goals."
        )
    if kind != "percent_income":
        return ""
    text = (raw_value or "").replace("%", "").strip()
    try:
        pct = float(text)
    except ValueError:
        return "Enter a percent, e.g. 10"
    if income_total <= 0:
        return (
            f"{pct:g}% of no confirmed income = $0.00/mo - confirm a paycheck "
            "under Bills & Income first."
        )
    monthly = round(income_total * pct / 100)
    return f"{pct:g}% of {_usd(income_total)}/mo = {_usd(monthly)}/mo"


def savings_goal_card(
    goal: dict[str, Any],
    *,
    on_contribute: Callable[[], Awaitable[None] | None],
    on_toggle_pause: Callable[[], Awaitable[None] | None],
    on_edit: Callable[[], Awaitable[None] | None],
    on_remove: Callable[[], Awaitable[None] | None],
) -> ft.Control:
    """One goal on the budget-line geometry, deliberately: name over a 4px
    strip with the percent top-right and "$saved of $target" under it -
    the Goals tab should read like a sibling of the Limits tab, not a
    different app. The goal-specific facts ride a fourth line (the ETA
    caption and the pause verb); everything else is the limits' own
    recipe, colours included. The card body clicks through to the editor,
    the same way a limit's bar opens its dial."""
    paused = goal.get("status") == "paused"
    progress = min(1.0, max(0.0, float(goal.get("progress") or 0)))
    bar_color = Theme.Colors.TEXT_SECONDARY if paused else _budget_status_color("good")
    body = ft.Column(
        [
            ft.Row(
                [
                    ft.Container(
                        content=ft.Row(
                            [
                                TableNameText(str(goal.get("name", ""))),
                                *(
                                    [Tag("linked", color=Theme.Colors.TEXT_SECONDARY)]
                                    if goal.get("funding") == "linked"
                                    else []
                                ),
                            ],
                            spacing=Theme.Spacing.SM,
                            tight=True,
                        ),
                        expand=True,
                    ),
                    NumericText(
                        f"{progress * 100:.0f}%",
                        size=Theme.Typography.BODY_SMALL,
                        color=Theme.Colors.TEXT_SECONDARY,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.ProgressBar(
                value=progress,
                height=4,
                color=bar_color,
                bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE),
                border_radius=2,
            ),
            ft.Row(
                [
                    SecondaryText(
                        goal_amounts_line(goal), size=Theme.Typography.BODY_SMALL
                    ),
                    ft.Container(expand=True),
                    SecondaryText(
                        goal_eta_caption(goal), size=Theme.Typography.BODY_SMALL
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ],
        spacing=Theme.Spacing.XS,
        tight=True,
    )
    return ft.Row(
        [
            ft.Container(
                content=body,
                expand=True,
                on_click=lambda _e: on_edit(),
                tooltip="Edit this goal",
            ),
            PulseButton(
                on_click_callable=on_toggle_pause,
                text="Resume" if paused else "Pause",
                variant="muted",
                compact=True,
            ),
            ActionMenu(
                [
                    ActionMenuItem(
                        "Add money", ft.Icons.ADD, lambda _e: on_contribute()
                    ),
                    ft.PopupMenuItem(),
                    ActionMenuItem(
                        "Remove",
                        ft.Icons.DELETE_OUTLINE,
                        lambda _e: on_remove(),
                        destructive=True,
                    ),
                ]
            ),
        ],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def envelope_card(
    envelope: dict[str, Any],
    *,
    on_spend: Callable[[], Awaitable[None] | None],
    on_credit: Callable[[], Awaitable[None] | None],
    on_edit: Callable[[], Awaitable[None] | None],
    on_remove: Callable[[], Awaitable[None] | None],
) -> ft.Control:
    """One envelope on the budget-family row geometry: name left, the
    BALANCE as the right-aligned figure (negative reads in error red -
    borrowed against next month is a fact worth seeing), the standing
    credit as a caption when it books itself. Spend is the primary verb -
    an allowance exists to be drawn down."""
    balance = envelope.get("balance", 0)
    caption = ""
    if envelope.get("auto_credit") and envelope.get("monthly_credit"):
        per = "wk" if envelope.get("cadence") == "weekly" else "mo"
        caption = f"+{_usd(envelope['monthly_credit'])}/{per}"
    body = ft.Column(
        [
            ft.Row(
                [
                    ft.Container(
                        content=TableNameText(str(envelope.get("name", ""))),
                        expand=True,
                    ),
                    NumericText(
                        _usd(balance),
                        size=Theme.Typography.BODY_LARGE,
                        color=(Theme.Colors.ERROR if balance < 0 else None),
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            SecondaryText(caption, size=Theme.Typography.BODY_SMALL)
            if caption
            else ft.Container(),
        ],
        spacing=Theme.Spacing.XS,
        tight=True,
    )
    return ft.Row(
        [
            ft.Container(
                content=body,
                expand=True,
                on_click=lambda _e: on_edit(),
                tooltip="Edit this envelope",
            ),
            PulseButton(
                on_click_callable=on_spend,
                text="Spend",
                variant="muted",
                compact=True,
            ),
            ActionMenu(
                [
                    ActionMenuItem("Add money", ft.Icons.ADD, lambda _e: on_credit()),
                    ft.PopupMenuItem(),
                    ActionMenuItem(
                        "Remove",
                        ft.Icons.DELETE_OUTLINE,
                        lambda _e: on_remove(),
                        destructive=True,
                    ),
                ]
            ),
        ],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def close_gap_row_copy(trim: dict[str, Any]) -> tuple[str, str, str]:
    """(title, signed delta, sub-line) for one Close-the-gap row.

    Two kinds, one shape: a goal pause RECOVERS its ask (positive, teal
    territory), a budget cut takes (negative, warning). The sub-line says
    what actually happens - a pause is not a deletion.
    """
    if trim.get("kind") == "pause_goal":
        return (
            f"Pause {trim.get('label', 'Goal')}",
            f"+{_usd(trim.get('recovered', 0))}",
            "on hold until you resume it",
        )
    return (
        str(trim.get("label", "")),
        f"-{_usd(trim.get('cut', 0))}",
        f"{_usd(trim.get('allocated_amount', 0))} -> "
        f"{_usd(trim.get('suggested_amount', 0))}",
    )


def linkable_account_options(accounts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(id, name) choices for "link an existing account": real, visible
    asset accounts only. A debt is not a dream, and goals don't nest."""
    return [
        (str(a["id"]), str(a.get("name", "")))
        for a in accounts
        if a.get("classification") == "asset"
        and a.get("account_type") != "goal"
        and not a.get("is_hidden")
        and a.get("id") is not None
    ]


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


def goal_suggestion_message(result: dict[str, Any]) -> str:
    """The parsed-goal sentence, from the service's data-only fields."""
    label = result.get("label") or "That"
    baseline = result.get("baseline_monthly") or 0
    suggested = result.get("suggested_limit") or 0
    fraction = result.get("fraction") or 0
    return (
        f"{label} has averaged {_usd(baseline)}/mo over the last 90 days. "
        f"Suggested limit: {_usd(suggested)}/mo "
        f"({int(fraction * 100)}% of baseline)."
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
