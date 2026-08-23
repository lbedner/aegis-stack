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

from datetime import date

import flet as ft

from app.components.frontend.controls import (
    H3Text,
    NumericText,
)

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
    _ACCOUNT_GROUPS,
    _DECLARED_FREQUENCY_LABELS,
    _FREQUENCY_LABELS,
    _MONTH_ABBREV,
    _TRADE_TYPE_LABELS,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    ledger_amount_color,
)
from app.components.frontend.theme import AegisTheme as Theme


def _usd(cents: int | None) -> str:
    value = (cents or 0) / 100
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _qty(shares: float | None) -> str:
    """Format a share quantity, trimming trailing zeros (10, 2.5, 0.125)."""
    return f"{float(shares or 0):g}"


def _yn(value: object) -> str | None:
    """'Yes'/'No' for a set flag, None when falsy (so it drops from detail)."""
    return "Yes" if value else None


def _type_label(account_type: str | None) -> str:
    return (account_type or "account").replace("_", " ").upper()


def _trade_type_label(trade_type: str | None) -> str:
    if not trade_type:
        return "-"
    return _TRADE_TYPE_LABELS.get(trade_type, trade_type.replace("_", " ").title())


def _category_leaf(name: str) -> str:
    """The last segment of a colon-hierarchical category name.

    Imported trees arrive as "Food & Dining:Groceries" - used where the
    parent prefix is noise (finance_recurring_tab.py's bill list shows
    leaf names only); the Categories tab still shows the full path when
    the hierarchy matters. NOT used by the Overview spending pie/list
    anymore - spending_by_category (domains/ledger/categories.py) already rolls
    those up to the PARENT segment before they ever reach here, so
    applying this on top would be a no-op at best.
    """
    return name.rsplit(":", 1)[-1].strip() if name else name


def _group_for(account_type: str) -> str:
    for label, types in _ACCOUNT_GROUPS:
        if account_type in types:
            return label
    return "Other"


def _parse_dollars(text: str) -> int:
    """Dollars string -> integer cents. Tolerates ``$``, commas, and blanks."""
    cleaned = (text or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return 0


def dollars_to_cents(raw: str | None) -> int | None:
    """ "$1,200.50" / "3,000" / " 12 " -> cents; junk -> None."""
    text = (raw or "").replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return round(float(text) * 100)
    except ValueError:
        return None


def _liability_line(account: dict) -> str | None:
    """Statement line under credit accounts ("Due Jul 15 · min $35.00").

    None when the institution reports nothing (the AMEX case) — the row then
    renders exactly as before, no empty widget.
    """
    liability = account.get("liability") or {}
    parts: list[str] = []
    due = liability.get("next_payment_due_date")
    if due:
        due_date = date.fromisoformat(due)
        parts.append(f"Due {due_date.strftime('%b')} {due_date.day}")
    minimum = liability.get("minimum_payment_amount")
    if minimum is not None:
        parts.append(f"min {_usd(minimum)}")
    return " · ".join(parts) if parts else None


def _account_display_balance(account: dict) -> int:
    """The balance to show for an account.

    Prefer the authoritative ``current_balance`` (Plaid/statement/valuation);
    for liabilities that figure is the amount owed, so show it negative. Fall
    back to the transaction-sum ``activity_balance`` when no balance was ever
    set (e.g. a CSV import with no running balance).

    "Never set" is subtle: accounts are CREATED with ``current_balance=0``,
    so a bare zero only counts as a real balance when ``balance_as_of``
    says a balance write actually happened. A nonzero value is trusted even
    unstamped (a hand-entered opening balance has no stamp).
    """
    current = account.get("current_balance")
    authoritative = current is not None and (
        current != 0 or account.get("balance_as_of")
    )
    if authoritative:
        if account.get("classification") == "liability":
            return -abs(current)
        return current
    return account.get("activity_balance") or 0


def _balance_color(cents: int | None) -> str:
    """Teal for positive, red for negative, muted for zero/unknown."""
    value = cents or 0
    if value > 0:
        return Theme.Colors.SUCCESS  # brand teal
    if value < 0:
        return Theme.Colors.ERROR
    return Theme.Colors.TEXT_SECONDARY


def _month_label(month_key: str) -> str:
    """``"2026-05"`` -> ``"May '26"``.

    A bare month number reads as a mystery integer on the axis, and the
    year matters the moment a window spans a January.
    """
    year, _, mon = str(month_key).partition("-")
    try:
        name = _MONTH_ABBREV[int(mon) - 1]
    except (ValueError, IndexError):
        return str(month_key)
    return f"{name} '{year[-2:]}" if len(year) == 4 else name


def _amount_cell(cents: int, *, excluded: bool = False) -> ft.Control:
    """Right-aligned money in the numeric face.

    A ledger is mostly spending, so an outflow is the ASSUMPTION and gets
    no colour - it would tint almost every row and point at nothing.
    Money coming IN is the exception, so that is what teal marks.

    Note this is the opposite rule from a BALANCE (see
    ``headline_stat_color``): a negative transaction is a normal Tuesday,
    a negative balance is being overdrawn.

    ``excluded`` (a row flagged out of reports - an issuer adjustment
    pair, a user exclusion) takes the money colour AWAY instead of adding
    a marker: an amount in muted ink says "does not participate" exactly
    where the eye scans, without spending a new element on it. A dot
    would collide with the status-dot vocabulary used elsewhere. The
    expand pane's "Excluded from reports" field carries the why.
    """
    return NumericText(
        _usd(cents),
        color=Theme.Colors.TEXT_SECONDARY if excluded else ledger_amount_color(cents),
        size=Theme.Typography.BODY_SMALL,
        weight=ft.FontWeight.W_500,
        text_align=ft.TextAlign.RIGHT,
    )


def _investment_section(title: str, table: ft.Control) -> ft.Control:
    """A labeled block (section heading + table) in the investment detail view."""
    return ft.Column([H3Text(title), table], spacing=Theme.Spacing.SM)


def _recurring_display_amount(stream: dict) -> int:
    """Signed cents for a recurring row: outflows negative, inflows positive."""
    amount = stream.get("average_amount") or 0
    return -amount if stream.get("direction") == "outflow" else amount


def _frequency_label(value: str) -> str:
    """Display text for a cadence, falling back to the raw value."""
    return (
        _FREQUENCY_LABELS.get(value) or _DECLARED_FREQUENCY_LABELS.get(value) or value
    )


def _budget_status_color(status: str) -> str:
    """Maps the backend's ``good``/``warn``/``critical`` (see
    ``budget_line_status`` in domains/domains/planning/budgets/lines.py) straight to a theme
    color - the 80%/100% thresholds are computed once, server-side; the
    frontend never recomputes them from raw numbers."""
    return {
        "critical": Theme.Colors.ERROR,
        "warn": Theme.Colors.WARNING,
    }.get(status, Theme.Colors.SUCCESS)


def _refresh_row(
    on_refresh,
    tooltip: str,
    leading: list[ft.Control] | None = None,
) -> ft.Control:
    """A right-aligned refresh icon-button, matching the pattern used by the
    other dashboard tabs. Flet holds UI state server-side, so a browser refresh
    won't re-fetch — this button re-pulls the data on demand. ``leading``
    controls (e.g. a Connect menu) sit just left of the refresh button."""
    return ft.Row(
        [
            ft.Container(expand=True),
            *(leading or []),
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                tooltip=tooltip,
                on_click=on_refresh,
            ),
        ],
        alignment=ft.MainAxisAlignment.END,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def target_note_copy(rule: str, raw_factor: str, resolved: int | None) -> str:
    """The goal dialog's line under a relative target - "3 months of
    expenses = $9,000.00". ``resolved`` is the server's answer, never a
    number this side computed: the question "3 months of WHAT" now has
    one authority, and the preview cannot disagree with the saved goal.
    Empty for a fixed target: the field already IS the answer."""
    if rule != "months_of_expenses":
        return ""
    try:
        months = int(float((raw_factor or "").strip()))
    except ValueError:
        months = 0
    if months <= 0:
        return "Enter a number of months, e.g. 3"
    if not resolved:
        return (
            "Nothing to size against on those accounts yet - add bills or "
            "budget lines, or set a fixed amount."
        )
    return f"{months} months of expenses = {_usd(resolved)}"


def goal_shortfall_caption(shortfall: int) -> str:
    """What the Budget header says when goals ask for money the month
    does not have. Names the gap rather than scolding: the plan is the
    user's, and a stretch goal is a legitimate thing to set."""
    if shortfall <= 0:
        return ""
    return f"Goals ask {_usd(shortfall)} more than this month has."
