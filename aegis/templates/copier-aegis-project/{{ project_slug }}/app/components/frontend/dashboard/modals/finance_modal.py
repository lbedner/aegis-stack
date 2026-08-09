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

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import flet as ft

from app.components.frontend.controls import (
    ActionDropdown,
    ActionMenu,
    ActionMenuItem,
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    ExpandArrow,
    H3Text,
    LabelText,
    MenuAction,
    NumericText,
    PrimaryText,
    SecondaryText,
    SectionCard,
    StatusDot,
    StatusTag,
    Tag,
    ThemedSwitch,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.debounce import Debouncer
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.dropdown import Dropdown
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.loading_overlay import LoadingOverlay
from app.components.frontend.controls.pickers import (
    BulkActionTrigger,
    CategoryPickerButton,
    CategoryPickerField,
    MerchantPickerButton,
    TagPickerButton,
    picker_trigger_cell,
)
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.record_detail import (
    HeroSpec,
    RecordDetailDialog,
    build_field_blocks,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings
from app.core.constants import dashboard_upload_dir
from app.core.formatting import format_date
from app.services.finance.constants import (
    CADENCES,
    ONE_TIME_FREQUENCY,
    ONE_TIME_LABEL,
)
from app.services.system.models import ComponentStatus, ComponentStatusType
from app.services.system.ui import get_component_title

from ..cards.card_utils import get_status_detail
from .base_detail_popup import BaseDetailPopup
from .base_popup import OverlayStyledDialog
from .finance_panel import FinancePanel
from .modal_sections import (
    PIE_CHART_TAIL_COLOR,
    BarChartCard,
    BarSeries,
    ChartColors,
    DateRangeChips,
    EmptyStatePlaceholder,
    LineChartCard,
    LineSeries,
    MetricCard,
    PieChartCard,
    RankedBar,
    RankedBarCard,
    chart_floor,
    date_cell,
    headline_stat,
    headline_stat_color,
    ledger_amount_color,
    status_dot,
)

_SIDEBAR_WIDTH = 320
# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
_PREVIEW_DETAIL_CAP = 10
_PREVIEW_DETAIL_HEIGHT = 260
# One height for every Overview card, so the row has a single baseline.
_OVERVIEW_CARD_HEIGHT = 320
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
_PIE_CATEGORIES = 15


class AccountFilter:
    """Which accounts the dashboard is currently looking at.

    ``selected`` is None for "all accounts" - the default. An EMPTY set is a
    legal staging state ("Remove all", then check the two you want) and the
    page renders empty rather than quietly falling back to everything.
    Owned by the finance dialog and shared with its tabs, so a narrower view
    can follow the user across tabs as more of them opt in.
    """

    def __init__(self) -> None:
        self.selected: set[int] | None = None

    @property
    def is_empty(self) -> bool:
        """Nothing checked - distinct from None, which means everything."""
        return self.selected is not None and not self.selected

    def allows(self, account_id: Any) -> bool:
        """Does this row survive the filter?

        A row with NO account always does. A bill or income typed in by
        hand has ``account_id = None``, and asking "is None among the
        chosen accounts" is always False - so any narrowing made every
        hand-entered row vanish from every tab at once. It belongs to no
        account, so no account selection is a statement about it.
        """
        if account_id is None:
            return True
        return self.selected is None or account_id in self.selected

    def params(self) -> dict[str, Any]:
        """Query params for endpoints that accept ``account_ids``.

        Never called for the empty state: an empty list would drop out of
        the query string and read as "no filter" server-side - the exact
        opposite of what an empty selection means. Callers check
        ``is_empty`` and skip the fetch instead.
        """
        if self.selected is None:
            return {}
        return {"account_ids": sorted(self.selected)}

    def toggle(self, account_id: int, all_ids: list[int]) -> None:
        current = set(self.selected) if self.selected is not None else set(all_ids)
        if account_id in current:
            current.discard(account_id)
        else:
            current.add(account_id)
        # Everything selected means the filter is off; empty stays empty.
        self.selected = None if current >= set(all_ids) else current


def _category_leaf(name: str) -> str:
    """The last segment of a colon-hierarchical category name.

    Imported trees arrive as "Food & Dining:Groceries" - used where the
    parent prefix is noise (finance_recurring_tab.py's bill list shows
    leaf names only); the Categories tab still shows the full path when
    the hierarchy matters. NOT used by the Overview spending pie/list
    anymore - spending_by_category (finance_service.py) already rolls
    those up to the PARENT segment before they ever reach here, so
    applying this on top would be a no-op at best.
    """
    return name.rsplit(":", 1)[-1].strip() if name else name


# account_type -> display group, in sidebar order (Quicken-style buckets).
_ACCOUNT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Banking", ("checking", "savings", "cash")),
    ("Credit Cards", ("credit_card",)),
    ("Investments", ("investment", "brokerage", "crypto")),
    ("Property", ("property", "vehicle")),
    ("Loans & Debt", ("loan", "other_liability")),
    ("Other", ("other_asset",)),
)


def _group_for(account_type: str) -> str:
    for label, types in _ACCOUNT_GROUPS:
        if account_type in types:
            return label
    return "Other"


# Account types whose detail view is holdings (positions), not transactions.
_INVESTMENT_TYPES = frozenset({"brokerage", "investment", "crypto"})

# Curated (account_type, label) choices for the manual "Add account" form. Keys
# are the DB-constrained account_type values; classification is derived below.
_ADD_ACCOUNT_TYPES: tuple[tuple[str, str], ...] = (
    ("checking", "Checking"),
    ("savings", "Savings"),
    ("cash", "Cash"),
    ("credit_card", "Credit card"),
    ("loan", "Loan"),
    ("brokerage", "Brokerage"),
    ("crypto", "Crypto"),
    ("property", "Property"),
    ("vehicle", "Vehicle"),
    ("other_asset", "Other asset"),
    ("other_liability", "Other liability"),
)
_LIABILITY_ACCOUNT_TYPES = frozenset({"credit_card", "loan", "other_liability"})


def _parse_dollars(text: str) -> int:
    """Dollars string -> integer cents. Tolerates ``$``, commas, and blanks."""
    cleaned = (text or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return 0


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


def _usd(cents: int | None) -> str:
    value = (cents or 0) / 100
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _qty(shares: float | None) -> str:
    """Format a share quantity, trimming trailing zeros (10, 2.5, 0.125)."""
    return f"{float(shares or 0):g}"


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


# Past about a dozen groups the bars thin to hairlines and the month
# labels collide, so a long window is FOLDED into coarser buckets rather
# than drawn as-is. Quarters up to ~3 years, then years.
_MAX_CASHFLOW_BARS = 12


_MONTH_ABBREV = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


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


def _fold_cashflow(months: list[dict]) -> list[dict]:
    """Group a monthly cashflow series into at most ``_MAX_CASHFLOW_BARS``.

    Returns rows carrying a display ``label`` alongside the summed income
    and expense. Short windows pass through untouched, labelled by month.
    """
    if len(months) <= _MAX_CASHFLOW_BARS:
        return [
            {**month, "label": _month_label(month.get("month", ""))} for month in months
        ]

    def bucket(month_key: str) -> str:
        year, _, mon = str(month_key).partition("-")
        if len(months) <= _MAX_CASHFLOW_BARS * 3:  # <= ~3 years -> quarters
            quarter = (int(mon or 1) - 1) // 3 + 1
            return f"Q{quarter} '{year[-2:]}"
        return year

    folded: dict[str, dict] = {}
    for month in months:
        key = bucket(month.get("month", ""))
        row = folded.setdefault(key, {"label": key, "income": 0, "expense": 0})
        row["income"] += month.get("income") or 0
        row["expense"] += month.get("expense") or 0
    return list(folded.values())


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


def _type_label(account_type: str | None) -> str:
    return (account_type or "account").replace("_", " ").upper()


_TRADE_TYPE_LABELS = {
    "buy": "Buy",
    "sell": "Sell",
    "dividend": "Dividend",
    "interest": "Interest",
    "fee": "Fee",
    "tax": "Tax",
    "transfer_in": "Transfer in",
    "transfer_out": "Transfer out",
    "deposit": "Deposit",
    "withdrawal": "Withdrawal",
    "reinvest": "Reinvest",
    "split": "Split",
    "cancel": "Cancel",
    "other": "Other",
}


def _trade_type_label(trade_type: str | None) -> str:
    if not trade_type:
        return "-"
    return _TRADE_TYPE_LABELS.get(trade_type, trade_type.replace("_", " ").title())


def _investment_section(title: str, table: ft.Control) -> ft.Control:
    """A labeled block (section heading + table) in the investment detail view."""
    return ft.Column([H3Text(title), table], spacing=Theme.Spacing.SM)


def _recurring_display_amount(stream: dict) -> int:
    """Signed cents for a recurring row: outflows negative, inflows positive."""
    amount = stream.get("average_amount") or 0
    return -amount if stream.get("direction") == "outflow" else amount


def _yn(value: object) -> str | None:
    """'Yes'/'No' for a set flag, None when falsy (so it drops from detail)."""
    return "Yes" if value else None


# --- Record -> tooltip / detail-section mappers -----------------------------
# These are the only transaction/trade-specific bits; DataTable's inline
# row-expand (and, for the one non-tabular surface left, RecordDetailDialog)
# is generic and shared across every table.


def transaction_tooltip(txn: dict) -> str:
    """Compact hover summary for a transaction row."""
    lines = [txn.get("name") or "Transaction", _usd(txn.get("amount", 0))]
    merchant = txn.get("merchant_name")
    if merchant and merchant != txn.get("name"):
        lines.append(merchant)
    # The transaction's actual resolved category, not Plaid's own raw
    # pfc_detailed/pfc_primary codes - see transaction_detail_sections's
    # own comment on this (same bug, same fix: those fields are empty
    # for anything not Plaid-synced, hiding a real category on CSV
    # imports and manual entries).
    category = txn.get("category")
    if category:
        lines.append(category)
    lines.append(str(txn.get("date", "")))
    if txn.get("pending"):
        lines.append("Pending")
    if txn.get("memo"):
        lines.append(f"Memo: {txn['memo']}")
    return "\n".join(lines)


def transaction_detail_hero(txn: dict) -> HeroSpec:
    """Payee/amount/date/status/category, promoted above the generic field
    list - what answers "what IS this transaction" at a glance, pulled out
    of ``transaction_detail_sections`` (see that function's own comment on
    why the rest stays a plain label/value list)."""
    amount = txn.get("amount", 0)
    meta = [format_date(txn.get("date"))]
    status = txn.get("status")
    if status:
        meta.append(str(status).title())
    return HeroSpec(
        primary=txn.get("name") or "Transaction",
        meta=" · ".join(meta),
        amount_text=_usd(amount),
        # Same rule the register rows already use (ledger_amount_color) -
        # an outflow is the assumption here too and gets no colour; only
        # money coming in is the exception worth marking.
        amount_color=ledger_amount_color(amount),
        chip_text=txn.get("category"),
    )


def transaction_detail_sections(
    txn: dict,
) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """Grouped label/value view of a transaction for the detail dialog -
    everything EXCEPT payee/amount/date/status/category, which
    ``transaction_detail_hero`` promotes above this list instead. Category
    source moves into "Import & reconciliation" (the caller marks that
    section collapsed) rather than sitting next to the category name
    itself - "rule"/"provider"/"user" is about HOW it got classified, a
    fact worth having but not one that competes with the classification
    itself for attention.
    """
    return [
        (
            "Details",
            [
                ("Merchant", txn.get("merchant_name")),
                ("Authorized", txn.get("authorized_date")),
                ("Posted", txn.get("posted_at")),
                ("Pending", _yn(txn.get("pending"))),
                ("Memo", txn.get("memo")),
                ("Check number", txn.get("check_number")),
                ("Payment channel", txn.get("payment_channel")),
                ("Original description", txn.get("original_description")),
            ],
        ),
        (
            "Import & reconciliation",
            [
                ("Category source", txn.get("category_source")),
                ("Source", txn.get("source")),
                ("External ID", txn.get("external_id")),
                ("Dedup status", txn.get("dedup_status")),
                ("Transfer", _yn(txn.get("is_transfer"))),
                ("Excluded from reports", _yn(txn.get("excluded_from_reports"))),
                ("Reversal", _yn(txn.get("is_reversal"))),
            ],
        ),
    ]


# Passed as RecordDetailDialog's collapsed_sections at every transaction
# detail call site - one constant so the section name can't drift out of
# sync between transaction_detail_sections's own list and each caller.
_TRANSACTION_COLLAPSED_SECTIONS = frozenset({"Import & reconciliation"})


def transaction_tag_chips(
    tags: list[dict],
    *,
    on_tap: Callable[[dict], None] | None = None,
    on_remove: Callable[[dict], None] | None = None,
    remove_tooltip: str = "Remove this tag",
    cap: int | None = None,
    compact: bool = False,
) -> list[ft.Control]:
    """A transaction's tags as house ``Tag`` chips.

    ``on_tap`` makes each chip a filter trigger (click a flag to see
    everything wearing it); ``on_remove`` pairs each chip with an ``x``
    (the row-expand detail is where a tag comes off); ``cap`` folds the
    tail into a "+n" so a register row stays one line."""
    shown = tags if cap is None else tags[:cap]
    chips: list[ft.Control] = []
    for tag in shown:
        chip: ft.Control = Tag(
            tag.get("name", ""),
            color=tag.get("color") or Theme.Colors.ACCENT,
            compact=compact,
        )
        if on_tap is not None:
            chip = ft.Container(
                content=chip,
                on_click=lambda _e, t=tag: on_tap(t),
                tooltip=f"Show everything tagged {tag.get('name', '')}",
            )
        if on_remove is not None:
            chip = ft.Row(
                [
                    chip,
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_size=14,
                        icon_color=Theme.Colors.TEXT_SECONDARY,
                        tooltip=remove_tooltip,
                        on_click=lambda _e, t=tag: on_remove(t),
                        style=ft.ButtonStyle(padding=0),
                        width=24,
                        height=24,
                    ),
                ],
                spacing=0,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        chips.append(chip)
    if cap is not None and len(tags) > cap:
        chips.append(
            SecondaryText(f"+{len(tags) - cap}", size=Theme.Typography.CAPTION)
        )
    return chips


async def fetch_tag_options(api) -> list[tuple[str, str]]:
    """The tag directory as picker options - keyed by NAME, not id: the
    attach endpoint is get-or-create by name, which is what lets a
    picker's pick and create share one handler."""
    data = await api.get("/api/v1/finance/tags")
    items = data if isinstance(data, list) else []
    return [(t["name"], t["name"]) for t in items]


async def post_tag(page: ft.Page, transaction_ids: list[int], name: str) -> bool:
    """Attach one tag to the given transactions and toast the outcome.

    The one POST every tagging surface goes through (the register and
    both Review work queues); returns whether it landed so the caller
    knows to reload."""
    from app.components.frontend.state.session_state import get_session_state

    api = get_session_state(page).api_client
    result = await api.post(
        "/api/v1/finance/transactions/tags",
        json={"transaction_ids": transaction_ids, "name": name},
    )
    if not isinstance(result, dict) or "id" not in result:
        ErrorSnackBar("Could not apply that tag.").launch(page)
        return False
    count = len(transaction_ids)
    SuccessSnackBar(
        f"Tagged {count} transaction{'s' if count != 1 else ''} {result['name']}."
    ).launch(page)
    return True


def _transaction_expanded_content(
    txn: dict, on_remove_tag: Callable[[dict, dict], None] | None = None
) -> ft.Control:
    """A transaction's inline row-expand content: the supplementary field
    sections only, no hero - unlike a modal (which starts from nothing),
    this renders directly under a row whose own cells already show payee/
    date/category/amount, so repeating those here would just be heavier
    for no new information.

    ``on_remove_tag(txn, tag)``, when given and the row wears tags, adds a
    Tags block whose chips each carry the remove ``x`` - taking a flag OFF
    happens here, next to everything else about the row."""
    blocks = build_field_blocks(
        transaction_detail_sections(txn),
        collapsed_sections=_TRANSACTION_COLLAPSED_SECTIONS,
    )
    tags = txn.get("tags") or []
    if tags and on_remove_tag is not None:
        blocks.append(
            ft.Row(
                [
                    SecondaryText("Tags", size=Theme.Typography.BODY_SMALL),
                    *transaction_tag_chips(
                        tags, on_remove=lambda t, _txn=txn: on_remove_tag(_txn, t)
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                wrap=True,
            )
        )
    return ft.Column(blocks, spacing=Theme.Spacing.XS, tight=True)


# One register fetch. Load more widens by another page of this.
_REGISTER_PAGE_SIZE = 100


def trades_within_page(
    trades: list[dict],
    *,
    oldest_txn_date: str | None,
    page_complete: bool,
) -> list[dict]:
    """The trades allowed into the merged register right now.

    Two lanes feed the register - paginated transactions, unpaginated
    trades - and merging them naively rendered trades far past the
    transaction page's edge: below the oldest fetched transaction the
    list became nothing but IRA trades, which read as "Chase and AMEX
    just stop after a certain date" (confirmed live). A lane may never
    show deeper than the other reaches; trades past the edge wait for
    Load more to extend it. A complete transaction lane (or a stack with
    no transactions at all) has no edge to respect.
    """
    if page_complete or oldest_txn_date is None:
        return trades
    return [t for t in trades if str(t.get("trade_date", "")) >= oldest_txn_date]


def register_count_label(
    shown: int | None, total: int, *, noun: str = "transactions"
) -> str:
    """The register's count line, honest about the page edge.

    "685 transactions" over a table rendering the newest 100 read as data
    loss - a mid-July row was "just not there at all" (confirmed live).
    A truncated view says "Showing 100 of 685" instead; the Load-more
    trigger rides beside this label in the header, because a bottom
    footer was tried first and permanently cost the table one row's
    height in a modal with none to spare.
    """
    if shown is not None and shown < total:
        return f"Showing {shown:,} of {total:,} {noun}"
    if noun == "transactions":
        return f"{total:,} transaction{'s' if total != 1 else ''}"
    return f"{total:,} {noun}"


def register_columns(all_accounts: bool) -> list[DataTableColumn]:
    """The register's columns. Account appears ONLY in All Accounts.

    With a single account selected every row would repeat its name, which
    is noise in the place it is least needed - the header above already
    says which account you are in. Same reasoning as the payee drill-down
    dropping its Payee column.

    Extracted so the count can be asserted against the row builder: the
    two are gated on the same flag, and a mismatch silently shifts every
    cell one column left.

    Payee is the identity column and cannot be hidden; Source is the
    least-read of the rest, so it ships hidden and is one click away in
    the column menu.
    """
    return [
        DataTableColumn("Date", width=120),
        *(
            [DataTableColumn("Account", width=200, style="secondary")]
            if all_accounts
            else []
        ),
        DataTableColumn("Payee", hideable=False),
        DataTableColumn("Category", width=_TXN_CATEGORY_COLUMN_WIDTH),
        DataTableColumn("Tags", width=150),
        DataTableColumn("Source", width=90, visible=False),
        DataTableColumn("Amount", width=150, alignment="right"),
    ]


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


def _preview_date_range(start: object, end: object) -> str:
    """The span an import covers, short enough to sit on ONE line.

    A metric card's caption is ~175px wide, and the house
    ``format_date`` twice over ("Jul 29, 2026 to Aug 6, 2026") does not
    fit - it wraps, which makes that card taller than the two beside it
    and leaves the row with a ragged bottom edge. Repeating the year is
    what it can afford to lose: a same-year range drops both (the file
    name carries it), a range that crosses one keeps both, because that
    is exactly when the year is the surprising part.
    """
    left, right = format_date(start), format_date(end)
    if not right or left == right:
        return left or right
    if left[-4:].isdigit() and left[-4:] == right[-4:]:
        left = left[:-6]
    return f"{left} to {right}"


def _preview_metric(
    label: str, count: int, caption: str, accent: str, tooltip: str
) -> MetricCard:
    """One outcome of an import, as the house metric card.

    NO icon, though ``MetricCard`` takes one: nothing else in the
    dashboard passes it, and a glyph beside the label reads as a
    different component rather than as emphasis. The label already says
    which of the three this is.

    A zero keeps the muted colour: nothing happened, so nothing should
    catch the eye. ``MetricCard`` leaves its number untinted by design
    (``color`` only ever tints the icon, so here it is inert), and a live
    count claims the colour back through ``set_value`` - three cards is
    few enough that a tinted number still means something, which is the
    condition that rule was written against.
    """
    live = count > 0
    color = accent if live else Theme.Colors.TEXT_SECONDARY
    card = MetricCard(
        label=label,
        value=f"{count:,}",
        color=color,
        prev_value=caption,
        tooltip=tooltip,
    )
    card.set_value(f"{count:,}", color)
    return card


def _preview_dot(text: str, live: bool, accent: str, tooltip: str) -> StatusDot:
    """An import outcome that does NOT touch the ledger, as a status dot.

    The house dot rather than a bordered chip: a chip's outline gives it a
    box of its own, which is the chrome the metric cards above use to say
    "this lands in your ledger". These do not. A zero keeps its dot and
    goes muted, so the row holds its shape either way.
    """
    return StatusDot(text, accent if live else Theme.Colors.TEXT_SECONDARY, tooltip)


def _import_count_controls(
    counts: dict[str, Any],
    *,
    headings: tuple[tuple[str, str], tuple[str, str], tuple[str, str]],
) -> tuple[ft.Row, ft.Row]:
    """(the three cards, the row of dots) for one set of import counts.

    Shared by the review dialog and the completion summary. They show the
    SAME five numbers, before and after, and a reader compares the two
    screens - so they are one layout wearing two sets of labels, not two
    layouts that drift into disagreeing about what a count means.

    ``headings`` supplies (label, caption) for add / update / duplicate,
    which is the whole difference between them: the review says what will
    happen, the summary says what did.
    """
    inserted = counts.get("rows_inserted", 0)
    updated = counts.get("rows_updated", 0)
    duplicate = counts.get("rows_duplicate", 0)
    skipped = counts.get("rows_skipped", 0)
    errors = counts.get("rows_error", 0)
    (add_label, add_note), (edit_label, edit_note), (have_label, have_note) = headings

    metrics = ft.Row(
        [
            _preview_metric(
                add_label,
                inserted,
                add_note,
                Theme.Colors.SUCCESS,
                "New transactions this file carries that your ledger does not.",
            ),
            _preview_metric(
                edit_label,
                updated,
                edit_note,
                Theme.Colors.WARNING,
                "Edited in your source app; changed in place, not duplicated.",
            ),
            _preview_metric(
                have_label,
                duplicate,
                have_note,
                Theme.Colors.TEXT_SECONDARY,
                "Matches a transaction already stored, so it is skipped.",
            ),
        ],
        spacing=Theme.Spacing.MD,
    )

    ignored = counts.get("rows_ignored", 0)
    dots: list[ft.Control] = [
        _preview_dot(
            f"{skipped:,} scheduled",
            bool(skipped),
            Theme.Colors.WARNING,
            "Not yet posted. Each one imports on its own once the payment clears.",
        ),
        *(
            [
                _preview_dot(
                    f"{ignored:,} from removed accounts",
                    True,
                    Theme.Colors.TEXT_SECONDARY,
                    "You removed these accounts, so their rows stay out. "
                    "Re-add the account to opt back in.",
                )
            ]
            if ignored
            else []
        ),
        _preview_dot(
            f"{errors:,} {'error' if errors == 1 else 'errors'}",
            bool(errors),
            Theme.Colors.ERROR,
            "Rows that could not be placed in an account.",
        ),
    ]
    kept = counts.get("category_kept_count", 0)
    if kept:
        # A dot too: three asides in one row read as one kind of thing,
        # and this is the same kind - something the import did NOT do to
        # the ledger.
        dots.append(
            _preview_dot(
                f"{kept:,} {'category' if kept == 1 else 'categories'} kept",
                True,
                Theme.Colors.SUCCESS,
                "You set these by hand, so the import leaves them as you set them.",
            )
        )
    return metrics, ft.Row(dots, spacing=Theme.Spacing.MD, wrap=True)


def _import_footnote(text: str) -> ft.Control:
    """The muted closing line all three import dialogs end on.

    The note EXPANDS. A Row hands its children unbounded width, so a note
    long enough to need a second line runs off the panel mid-sentence
    instead of wrapping inside it. START, not CENTER: centred against a
    two-line note the icon floats into the gap between the lines.
    """
    return ft.Row(
        [
            ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=Theme.Colors.TEXT_SECONDARY),
            ft.Container(
                content=SecondaryText(text, size=Theme.Typography.BODY_SMALL),
                expand=True,
            ),
        ],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def import_identical_body(preview: dict[str, Any], file_name: str) -> ft.Column:
    """The body for a file that was already imported, byte for byte.

    The third state of the same dialog, so it keeps the family's shape:
    the same subtitle line, the same dot vocabulary, the same closing
    note. It stays SMALL because it is a dead end - one button, nothing
    to decide - and gets no metric cards, since a row of zeroes wearing
    the chrome that means "this reaches your ledger" says the opposite of
    what happened.

    The reason carries the message, not the count. "0 changes" on its own
    reads as a failed import; what the reader needs is that this exact
    file already went in.
    """
    return ft.Column(
        [
            SecondaryText(
                f"{preview.get('rows_total', 0):,} rows read from {file_name}",
                size=Theme.Typography.BODY_SMALL,
            ),
            ft.Row(
                [
                    _preview_dot(
                        "0 changes",
                        False,
                        Theme.Colors.TEXT_SECONDARY,
                        "Every row in this file is already in your ledger.",
                    ),
                    _preview_dot(
                        "identical file",
                        False,
                        Theme.Colors.TEXT_SECONDARY,
                        "Matched by content hash, so a rename would not fool it.",
                    ),
                ],
                spacing=Theme.Spacing.MD,
                wrap=True,
            ),
            # Short: the dots above already carry "identical" and "no
            # changes", so this only has to say WHY, once.
            _import_footnote(
                "Nothing has been written. You already imported this exact file."
            ),
        ],
        spacing=Theme.Spacing.MD,
        tight=True,
    )


def import_summary_body(result: dict[str, Any]) -> ft.Column:
    """The body of the "Import complete" dialog: what the run just did.

    Deliberately the review dialog's own layout in the past tense. This
    opens seconds after that one closed, showing the same five numbers,
    and the reader's question is "did it do what it said" - which is a
    comparison, and only works if the two screens are shaped alike.
    """
    metrics, dots = _import_count_controls(
        result,
        headings=(
            ("Added", "Now in your ledger"),
            ("Updated", "Changed in place"),
            ("Already had", "Left alone"),
        ),
    )
    return ft.Column(
        [
            SecondaryText(
                f"{result.get('rows_total', 0):,} rows read from the file",
                size=Theme.Typography.BODY_SMALL,
            ),
            metrics,
            dots,
        ],
        spacing=Theme.Spacing.MD,
        tight=True,
    )


# The sentinel option key for "create a new account" in the investment
# import's target picker. A string because FormDropdown keys are strings;
# real accounts ride as str(id).
_NEW_ACCOUNT_KEY = "new"


def investment_target_options(
    accounts: list[dict[str, Any]], selected_id: int | None
) -> tuple[list[tuple[str, str]], str]:
    """(options, default key) for the investment import's account picker.

    Only investment-typed accounts are offered - aiming a trade ledger at
    a checking account is never right - plus a create-new entry, so the
    picker is never a dead end on a fresh project with no brokerage
    accounts at all. The default follows the sidebar selection only when
    that selection is itself an investment account; otherwise it lands on
    create-new rather than guessing.
    """
    options = [
        (str(a["id"]), str(a.get("name", "")))
        for a in accounts
        if a.get("account_type") in _INVESTMENT_TYPES and a.get("id") is not None
    ]
    options.append((_NEW_ACCOUNT_KEY, "Create a new account..."))
    default = _NEW_ACCOUNT_KEY
    if selected_id is not None and any(k == str(selected_id) for k, _ in options):
        default = str(selected_id)
    return options, default


def _suggested_account_name(file_name: str) -> str:
    """A starting name for a to-be-created account, from the file name.

    The ledger itself never names its account, so the file name is the
    only hint there is. Cleaned (extension off, separators to spaces,
    title-cased) purely as a prefill - the field stays editable.
    """
    stem = file_name.rsplit(".", 1)[0]
    cleaned = " ".join(stem.replace("-", " ").replace("_", " ").split())
    return cleaned.title() if cleaned else "Investment Account"


def investment_import_preview_body(preview: dict[str, Any]) -> ft.Column:
    """What a parsed ledger replays to: row count, date range, ending
    position and value per security, and the total. The dialog's facts
    section - the account choice below it is made looking at these.

    Values are at each security's last LEDGER price (the same mark the
    import will store), which the header names so a months-stale figure
    isn't mistaken for a live quote. Name in primary ink, value as the
    right-aligned figure; the share count is the supporting detail
    between them, so it wears the secondary colour.
    """
    positions = preview.get("positions") or []
    rows: list[ft.Control] = [
        ft.Row(
            [
                PrimaryText(str(p.get("name", "")), size=Theme.Typography.BODY_SMALL),
                ft.Container(expand=True),
                NumericText(
                    f"{p.get('shares', 0):,.3f} shares",
                    size=Theme.Typography.BODY_SMALL,
                    color=Theme.Colors.TEXT_SECONDARY,
                ),
                ft.Container(width=Theme.Spacing.MD),
                NumericText(
                    _usd(p.get("value", 0)),
                    size=Theme.Typography.BODY_SMALL,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        for p in positions
        if p.get("shares")  # exchanged-away share classes replay to zero
    ]
    first = format_date(preview.get("first_date"))
    last = format_date(preview.get("last_date"))
    # The total closes the column the values ran down, where a reader's
    # eye lands after scanning the rows - in the accent teal, since it is
    # the one number the whole section exists to answer.
    total_row = ft.Row(
        [
            SecondaryText(
                "Total at the ledger's last prices", size=Theme.Typography.BODY_SMALL
            ),
            ft.Container(expand=True),
            NumericText(
                _usd(preview.get("total_value", 0)),
                size=Theme.Typography.BODY_SMALL,
                color=Theme.Colors.ACCENT,
                weight=ft.FontWeight.W_600,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return ft.Column(
        [
            SecondaryText(
                f"{preview.get('activities_parsed', 0):,} activities, "
                f"{first} to {last}",
                size=Theme.Typography.BODY_SMALL,
            ),
            ft.Container(height=Theme.Spacing.XS),
            *rows,
            ft.Divider(height=1, color=Theme.Colors.BORDER_SUBTLE),
            total_row,
        ],
        spacing=Theme.Spacing.XS,
        tight=True,
    )


def investment_import_summary_body(result: dict[str, Any]) -> ft.Column:
    """The body of an investment-ledger "Import complete" dialog.

    A lighter cousin of ``import_summary_body``: a ledger import has no
    scheduled/error/skipped rows in the register's sense, so it earns two
    cards, not three, rather than forcing the register's exact vocabulary
    onto a shape that doesn't carry it.
    """
    inserted = result.get("trades_inserted", 0)
    updated = result.get("trades_updated", 0)
    created = result.get("securities_created", 0)
    metrics = ft.Row(
        [
            _preview_metric(
                "Trades added",
                inserted,
                "Now in your ledger",
                Theme.Colors.SUCCESS,
                "New activity this file carries that your ledger does not.",
            ),
            _preview_metric(
                "Trades updated",
                updated,
                "Changed in place",
                Theme.Colors.WARNING,
                "Matched an existing row and replaced it.",
            ),
            _preview_metric(
                "Securities added",
                created,
                "New to the catalog",
                Theme.Colors.TEXT_SECONDARY,
                "Funds this account hadn't held before.",
            ),
        ],
        spacing=Theme.Spacing.MD,
    )
    return ft.Column(
        [
            SecondaryText(
                f"{result.get('activities_parsed', 0):,} rows read from the file",
                size=Theme.Typography.BODY_SMALL,
            ),
            metrics,
        ],
        spacing=Theme.Spacing.MD,
        tight=True,
    )


def _preview_tag_row(kind: str, name: str, color: str) -> ft.Control:
    """One named thing in a preview section: a kind tag beside its name."""
    return ft.Row(
        [Tag(kind, color=color), SecondaryText(name, no_wrap=True)],
        spacing=Theme.Spacing.SM,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _preview_creates(preview: dict[str, Any]) -> list[ft.Control]:
    """Rows naming what a commit would MINT, not just count.

    An import that quietly invents an account is the surprise this dialog
    exists to head off, so each one is named. Categories are capped: a
    Quicken tree can carry hundreds, and a dialog that scrolls for a page
    stops being read at all.
    """
    rows: list[ft.Control] = []
    rows.extend(
        _preview_tag_row("Account", name, Theme.Colors.WARNING)
        for name in preview.get("new_accounts") or []
    )
    categories = preview.get("new_categories") or []
    rows.extend(
        _preview_tag_row("Category", name, Theme.Colors.TEXT_SECONDARY)
        for name in categories[:_PREVIEW_DETAIL_CAP]
    )
    if len(categories) > _PREVIEW_DETAIL_CAP:
        rows.append(
            SecondaryText(
                f"and {len(categories) - _PREVIEW_DETAIL_CAP:,} more categories",
                size=Theme.Typography.BODY_SMALL,
            )
        )
    return rows


def _preview_edits(preview: dict[str, Any]) -> list[ft.Control]:
    """One row per in-place update: when, how much, what changed.

    An edit is the only outcome here that rewrites something already
    stored, so it is spelled out field by field rather than counted - a
    number alone gives no way to tell a payee tidy-up from a
    re-categorization you did not ask for.
    """
    edits = preview.get("edits") or []
    rows: list[ft.Control] = []
    for edit in edits[:_PREVIEW_DETAIL_CAP]:
        rows.append(
            ft.Row(
                [
                    ft.Container(
                        content=SecondaryText(
                            format_date(edit.get("date")),
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        width=90,
                    ),
                    ft.Container(
                        content=NumericText(
                            _usd(abs(edit.get("amount", 0))),
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        width=80,
                        alignment=ft.alignment.center_right,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                PrimaryText(
                                    edit.get("name") or "transaction",
                                    size=Theme.Typography.BODY_SMALL,
                                    no_wrap=True,
                                ),
                                SecondaryText(
                                    "; ".join(edit.get("changes") or []),
                                    size=Theme.Typography.CAPTION,
                                ),
                            ],
                            spacing=0,
                            tight=True,
                        ),
                        expand=True,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
    if len(edits) > _PREVIEW_DETAIL_CAP:
        rows.append(
            SecondaryText(
                f"and {len(edits) - _PREVIEW_DETAIL_CAP:,} more updates",
                size=Theme.Typography.BODY_SMALL,
            )
        )
    return rows


def import_preview_body(preview: dict[str, Any], file_name: str) -> ft.Column:
    """The body of the import review dialog: what a commit would do.

    Built as house controls rather than a column of sentences, because the
    shape carries the meaning. The three outcomes that CHANGE the ledger
    are metric cards; the two that do not (scheduled, errors) are chips,
    so a skipped row can never be read as an incoming one. The per-account
    split is the ranked-bar card, which answers "where does this land"
    with a glance instead of a list to be added up by eye.

    Pure and module-level so the coverage property - every count the
    preview carries reaches the screen - can be asserted directly.
    """
    added_note = "New transactions"
    if preview.get("rows_inserted", 0) and preview.get("insert_date_start"):
        added_note = _preview_date_range(
            preview.get("insert_date_start"), preview.get("insert_date_end")
        )
    metrics, dot_row = _import_count_controls(
        preview,
        headings=(
            ("To add", added_note),
            ("To update", "Changed in place"),
            ("Already have", "Left alone"),
        ),
    )

    sections: list[ft.Control] = []
    by_account = preview.get("inserts_by_account") or {}
    # One bar is not a ranking, it is "To add" restated.
    if len(by_account) > 1:
        sections.append(
            RankedBarCard(
                title="Where the new rows land",
                rows=[
                    RankedBar(label=name, value=float(count), display=f"{count:,}")
                    for name, count in sorted(
                        by_account.items(), key=lambda item: -item[1]
                    )
                ],
            )
        )
    creates = _preview_creates(preview)
    if creates:
        sections.append(
            SectionCard(
                title="Also creates",
                body=ft.Column(creates, spacing=Theme.Spacing.XS, tight=True),
                body_padding=Theme.Spacing.MD,
            )
        )
    removed = preview.get("removed_accounts") or []
    if removed:
        sections.append(
            SectionCard(
                title="Staying out",
                body=ft.Column(
                    [
                        SecondaryText(
                            "You removed these accounts, so their rows are "
                            "ignored. Re-add an account to import into it "
                            "again.",
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        *(
                            _preview_tag_row(
                                "Account", name, Theme.Colors.TEXT_SECONDARY
                            )
                            for name in removed
                        ),
                    ],
                    spacing=Theme.Spacing.XS,
                    tight=True,
                ),
                body_padding=Theme.Spacing.MD,
            )
        )
    edits = _preview_edits(preview)
    if edits:
        sections.append(
            SectionCard(
                title="Updated in place",
                body=ft.Column(edits, spacing=Theme.Spacing.XS, tight=True),
                body_padding=Theme.Spacing.MD,
            )
        )

    children: list[ft.Control] = [
        SecondaryText(
            f"{preview.get('rows_total', 0):,} rows read from {file_name}",
            size=Theme.Typography.BODY_SMALL,
        ),
        metrics,
        dot_row,
    ]
    if sections:
        children.append(
            ft.Container(
                content=ft.Column(
                    sections,
                    spacing=Theme.Spacing.SM,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                height=_PREVIEW_DETAIL_HEIGHT,
            )
        )
    children.append(_import_footnote("Nothing has been written yet."))
    return ft.Column(children, spacing=Theme.Spacing.MD, tight=True)


def transaction_table(
    items: list[dict],
    *,
    account_names: dict[int, str] | None = None,
    scroll_height: int | None = 560,
    expand: bool = False,
    show_category: bool = False,
    payee_column: bool = True,
    empty_message: str = "No transactions.",
) -> DataTable:
    """The house transaction table: Date, Account, who, [Category], Amount,
    dense rows, click a row to expand its full detail inline.

    This shape had been retyped per surface - the register, Uncategorized,
    No payee, the recurring preview - which is how they drifted to three
    different Account widths and two different date formats. New surfaces
    call this instead of copying the nearest one.

    ``expand=True`` fills whatever panel it is in instead of claiming a
    fixed height - the right choice when the table IS the page, since a
    fixed one both wastes a tall window and slices its last row in half.

    ``payee_column=False`` swaps the third column from the resolved payee
    to the raw descriptor. That is the right column when the payee is
    already the thing being filtered on: repeating "Target" down a
    thousand rows says nothing, while the descriptors underneath it are
    exactly what you came to look at.
    """
    names = account_names or {}
    columns = [
        DataTableColumn("Date", width=110),
        DataTableColumn("Account", width=220, style="secondary"),
        DataTableColumn("Payee" if payee_column else "Description", hideable=False),
    ]
    if show_category:
        columns.append(DataTableColumn("Category", width=220, style="secondary"))
    columns.append(DataTableColumn("Amount", width=130, alignment="right"))

    rows: list[list[ft.Control]] = []
    for txn in items:
        cells: list[ft.Control] = [
            date_cell(txn.get("date")),
            TableCellText(names.get(txn.get("account_id"), "—")),
            TableNameText(
                (txn.get("merchant") or txn.get("name") or "")
                if payee_column
                else (txn.get("name") or txn.get("original_description") or "")
            ),
        ]
        if show_category:
            cells.append(TableCellText(txn.get("category") or "Uncategorized"))
        cells.append(
            _amount_cell(
                txn.get("amount", 0),
                excluded=bool(txn.get("excluded_from_reports")),
            )
        )
        rows.append(cells)

    def _expand(idx: int, _items: list = items) -> ft.Control:
        return _transaction_expanded_content(_items[idx])

    return DataTable(
        columns=columns,
        rows=rows,
        row_padding=6,
        item_extent=_DENSE_ROW_HEIGHT,
        scroll_height=None if expand else scroll_height,
        expand=expand,
        expandable_content=_expand,
        column_picker=True,
        empty_message=empty_message,
    )


def _trade_expanded_content(trade: dict) -> ft.Control:
    """A trade's inline row-expand content - same reasoning as
    ``_transaction_expanded_content``; trades never had a hero to begin
    with (not spending, no category), so this is a straight port."""
    return ft.Column(
        build_field_blocks(trade_detail_sections(trade)),
        spacing=Theme.Spacing.XS,
        tight=True,
    )


def trade_detail_sections(
    trade: dict,
) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """Full grouped label/value view of a trade for the detail dialog."""
    return [
        (
            "Activity",
            [
                ("Type", _trade_type_label(trade.get("type"))),
                ("Subtype", trade.get("subtype")),
                ("Description", trade.get("name")),
                ("Date", format_date(trade.get("trade_date"))),
            ],
        ),
        (
            "Amounts",
            [
                (
                    "Quantity",
                    _qty(trade.get("quantity")) if trade.get("quantity") else None,
                ),
                ("Price", _usd(trade.get("price")) if trade.get("price") else None),
                ("Amount", _usd(trade.get("amount", 0))),
                ("Fees", _usd(trade.get("fees")) if trade.get("fees") else None),
                ("Currency", (trade.get("currency") or "").upper() or None),
            ],
        ),
    ]


def _import_menu(
    on_transactions: Callable[[ft.ControlEvent], None],
    on_investments: Callable[[ft.ControlEvent], None],
) -> ActionDropdown:
    """Compact "Import" pill: an explicit choice of file kind instead of
    guessing it from whichever account happens to be selected.

    The guess broke down as soon as a second file shape existed - a
    brokerage account selected by habit while importing a bank statement
    (or vice versa) would silently route to the wrong parser. Each item
    also names what it accepts, so the format is known before a file is
    even picked rather than discovered from a rejected upload.
    """
    return ActionDropdown(
        "Import",
        [
            MenuAction(
                "Transactions",
                ft.Icons.RECEIPT_LONG,
                on_transactions,
                caption="OFX, QFX, QIF, CSV",
            ),
            MenuAction(
                "Investments",
                ft.Icons.SHOW_CHART,
                on_investments,
                caption="Optum HSA activity (CSV, TSV)",
            ),
        ],
        tooltip="Import a file",
    )


def _build_connect_menu(on_bank, on_brokerage) -> ActionDropdown | None:
    """The provider Connect menu, shared by the Accounts sidebar and the
    Connections tab header.

    Items appear whenever the provider capability is built into the stack
    (``settings.FINANCE_PLAID`` / ``FINANCE_SNAPTRADE``), not when
    credentials are set: hiding the menu on a fresh project with an empty
    ``.env`` made the feature's front door invisible. Missing credentials
    fail helpfully at click time instead (see the connect flows)."""
    actions: list[MenuAction] = []
    if settings.FINANCE_PLAID:
        actions.append(
            MenuAction("Connect a bank", ft.Icons.ACCOUNT_BALANCE_OUTLINED, on_bank)
        )
    if settings.FINANCE_SNAPTRADE:
        actions.append(
            MenuAction("Connect a brokerage", ft.Icons.SHOW_CHART, on_brokerage)
        )
    if not actions:
        return None
    return ActionDropdown("Connect", actions, tooltip="Connect an institution")


async def _connect_bank_flow(
    page: ft.Page, reload: Callable[[], Awaitable[None]]
) -> None:
    """Plaid Hosted Link: open Plaid's hosted connect page in a new tab, then
    poll server-side (~2.5 min) and reload the caller's view when the
    connection lands. (In sandbox mode the test credentials live on the
    Connections tab's Plaid card.)"""
    if not (settings.PLAID_CLIENT_ID and settings.PLAID_SECRET):
        ErrorSnackBar(
            "Plaid isn't configured yet: set PLAID_CLIENT_ID and PLAID_SECRET "
            "in .env, then restart."
        ).launch(page)
        return
    from app.components.frontend.state.session_state import get_session_state

    api = get_session_state(page).api_client
    started = await api.post("/api/v1/finance/plaid/hosted-link", json={})
    if not (isinstance(started, dict) and started.get("hosted_link_url")):
        ErrorSnackBar("Could not start Plaid.").launch(page)
        return
    page.launch_url(started["hosted_link_url"], web_window_name="_blank")
    SuccessSnackBar(
        "Complete the connection in the new tab; your accounts will "
        "appear here automatically."
    ).launch(page)
    link_token = started["link_token"]
    for _ in range(50):
        await asyncio.sleep(3)
        done = await api.post(
            "/api/v1/finance/plaid/hosted-link/complete",
            json={"link_token": link_token},
        )
        if isinstance(done, dict) and done.get("connections", 0) > 0:
            synced = sum(r.get("added", 0) for r in done.get("results", []))
            await reload()
            SuccessSnackBar(f"Bank connected — {synced} transactions synced.").launch(
                page
            )
            return


async def _connect_brokerage_flow(
    page: ft.Page, reload: Callable[[], Awaitable[None]]
) -> None:
    """SnapTrade connection portal: open it in a new tab, then poll
    server-side (~2.5 min) until the new authorization lands and reload the
    caller's view."""
    if not (settings.SNAPTRADE_CLIENT_ID and settings.SNAPTRADE_CONSUMER_KEY):
        ErrorSnackBar(
            "SnapTrade isn't configured yet: set SNAPTRADE_CLIENT_ID and "
            "SNAPTRADE_CONSUMER_KEY in .env, then restart."
        ).launch(page)
        return
    from app.components.frontend.state.session_state import get_session_state

    api = get_session_state(page).api_client
    started = await api.post("/api/v1/finance/snaptrade/connect", json={})
    if not (isinstance(started, dict) and "redirect_uri" in started):
        ErrorSnackBar("Could not start the brokerage connection.").launch(page)
        return
    if started["redirect_uri"]:
        page.launch_url(started["redirect_uri"], web_window_name="_blank")
        SuccessSnackBar(
            "Complete the connection in the new tab; your accounts will "
            "appear here automatically."
        ).launch(page)
    else:
        # Personal-key mode: no portal - brokerages are linked in
        # SnapTrade's dashboard and the poll below adopts what exists.
        SuccessSnackBar("Checking SnapTrade for your connected brokerages...").launch(
            page
        )
    for _ in range(50):
        await asyncio.sleep(3)
        done = await api.post("/api/v1/finance/snaptrade/connect/complete", json={})
        if isinstance(done, dict) and done.get("connections", 0) > 0:
            holdings = sum(r.get("holdings", 0) for r in done.get("results", []))
            await reload()
            SuccessSnackBar(
                f"Brokerage connected — {holdings} holdings synced."
            ).launch(page)
            return


class AccountsSidebar(ft.Container):
    """Grouped, clickable account list. Calls ``on_select(account | None)`` with
    the full account dict (``None`` for the "All Accounts" row)."""

    def __init__(
        self,
        page: ft.Page,
        on_select,
        on_import_transactions=None,
        on_import_investments=None,
    ) -> None:
        super().__init__()
        self.page = page
        self._on_select = on_select
        self.width = _SIDEBAR_WIDTH
        self.bgcolor = Theme.Colors.SURFACE_1
        self.border = ft.border.only(right=ft.BorderSide(1, Theme.Colors.BORDER_SUBTLE))
        self.padding = ft.padding.symmetric(vertical=Theme.Spacing.SM)
        self._list = ft.Column(spacing=3, scroll=ft.ScrollMode.AUTO, expand=True)
        # One row, setup order: create a manual account, link a provider,
        # backfill from a file. Labels stay short so all three fit the
        # sidebar's width; tooltips carry the detail the labels drop.
        # (Tooltips are set as attributes: the button base stores extra
        # kwargs without applying them.)
        add_button = PulseButton(
            on_click_callable=self._open_add_account,
            text="Add",
            variant="teal",
            compact=True,
        )
        add_button.tooltip = "Add a manual account"
        actions: list[ft.Control] = [add_button]
        # Provider connects live in one compact menu; each item appears only
        # when its provider is configured (the flag/creds exist).
        connect = _build_connect_menu(
            lambda e: e.page.run_task(self._connect_bank),
            lambda e: e.page.run_task(self._connect_brokerage),
        )
        if connect is not None:
            actions.append(connect)
        # File import lives with the other account-level actions; the
        # import itself targets whichever account is selected in this list.
        # A dropdown, not a single button: the file kind (register vs.
        # investment ledger) is an explicit pick, not guessed from the
        # selection - see _import_menu's docstring for why that broke.
        if on_import_transactions is not None and on_import_investments is not None:
            actions.append(
                _import_menu(
                    lambda e: e.page.run_task(on_import_transactions),
                    lambda e: e.page.run_task(on_import_investments),
                )
            )
        # No "ACCOUNTS" heading: the tab is already named Accounts, so the
        # header is just the action row, refresh pushed to the far edge.
        actions.append(ft.Container(expand=True))
        actions.append(
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                icon_size=18,
                tooltip="Refresh accounts",
                on_click=lambda e: e.page.run_task(self.reload),
            )
        )
        self.content = ft.Column(
            [
                ft.Container(
                    content=ft.Row(
                        actions,
                        spacing=Theme.Spacing.SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.only(
                        left=Theme.Spacing.MD,
                        right=Theme.Spacing.SM,
                        top=Theme.Spacing.XS,
                        bottom=Theme.Spacing.SM,
                    ),
                ),
                self._list,
            ],
            spacing=0,
            expand=True,
        )
        self._rows: dict[object, ft.Container] = {}
        self._accounts: dict[int, dict] = {}
        self._selected: object = None

    def did_mount(self) -> None:
        if self.page:
            self.page.run_task(self._load)

    def _group_header(self, text: str, subtotal: int) -> ft.Container:
        return ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        text,
                        size=Theme.Typography.CAPTION,
                        color=Theme.Colors.TEXT_SECONDARY,
                        weight=ft.FontWeight.W_600,
                        expand=True,
                    ),
                    NumericText(
                        _usd(subtotal),
                        size=Theme.Typography.BODY_SMALL,
                        color=_balance_color(subtotal),
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=Theme.Spacing.MD,
            ),
            padding=ft.padding.only(
                left=Theme.Spacing.MD,
                right=Theme.Spacing.MD,
                top=Theme.Spacing.MD,
                bottom=Theme.Spacing.XS,
            ),
        )

    def _row(
        self,
        key: object,
        label: str,
        balance: int | None,
        *,
        indent: int = Theme.Spacing.MD,
        bold: bool = False,
        subtitle: str | None = None,
    ) -> ft.Container:
        name = ft.Text(
            label,
            size=Theme.Typography.BODY_SMALL,
            color=Theme.Colors.TEXT_PRIMARY,
            weight=ft.FontWeight.W_600 if bold else ft.FontWeight.W_400,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        left: ft.Control
        if subtitle:
            left = ft.Column(
                [
                    name,
                    ft.Text(
                        subtitle,
                        size=Theme.Typography.CAPTION,
                        color=Theme.Colors.TEXT_SECONDARY,
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=1,
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            )
        else:
            name.expand = True
            left = name
        # Individual account rows read in the primary text color - teal is
        # reserved for TOTALS (group subtotals + the bold All Accounts
        # row), so the sidebar isn't a wall of accent. RED is not: an
        # overdrawn checking account is trouble at any level, and a plain
        # white "-$222.56" read as ordinary (headline_stat_color's rule -
        # colour the number in trouble, never every healthy one).
        if bold:
            balance_color = _balance_color(balance)
        elif balance is not None and balance < 0:
            balance_color = Theme.Colors.ERROR
        else:
            balance_color = Theme.Colors.TEXT_PRIMARY
        bal = NumericText(
            _usd(balance) if balance is not None else "",
            size=Theme.Typography.BODY_SMALL,
            color=balance_color,
        )
        row = ft.Container(
            content=ft.Row([left, bal], spacing=Theme.Spacing.MD),
            padding=ft.padding.only(
                left=indent,
                right=Theme.Spacing.MD,
                top=Theme.Spacing.SM + 2,
                bottom=Theme.Spacing.SM + 2,
            ),
            border_radius=Theme.Components.BUTTON_RADIUS,
            ink=True,
            data=key,
            on_click=lambda _e, k=key: self._select(k),
            on_hover=self._hover,
        )
        self._rows[key] = row
        return row

    def _hover(self, event: ft.ControlEvent) -> None:
        control = event.control
        if control.data == self._selected:
            return
        control.bgcolor = Theme.Colors.SURFACE_2 if event.data == "true" else None
        control.update()

    def _select(self, key: object) -> None:
        self._selected = key
        for row_key, row in self._rows.items():
            row.bgcolor = Theme.Colors.SURFACE_3 if row_key == key else None
            if row.page is not None:
                row.update()
        account = self._accounts.get(key) if isinstance(key, int) else None
        self._on_select(account)

    async def _load(self, select_id: object = None) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/finance/accounts", params={"page_size": 200})
        items = data.get("items", []) if isinstance(data, dict) else []

        self._list.controls.clear()
        self._rows.clear()
        self._accounts = {a["id"]: a for a in items}

        total = sum(_account_display_balance(a) for a in items)
        self._list.controls.append(self._row(None, "All Accounts", total, bold=True))

        grouped: dict[str, list] = {}
        for account in items:
            grouped.setdefault(_group_for(account.get("account_type", "")), []).append(
                account
            )
        for label, _types in _ACCOUNT_GROUPS:
            group = grouped.get(label)
            if not group:
                continue
            subtotal = sum(_account_display_balance(a) for a in group)
            self._list.controls.append(self._group_header(label, subtotal))
            for account in sorted(group, key=_account_display_balance, reverse=True):
                self._list.controls.append(
                    self._row(
                        account["id"],
                        account.get("name", ""),
                        _account_display_balance(account),
                        subtitle=_liability_line(account),
                    )
                )
        if self._list.page is not None:
            self._list.update()
        # Re-select the requested account if it still exists, else the combined
        # view (used after a rename keeps you where you were; a remove drops you
        # back to All Accounts).
        self._select(select_id if select_id in self._rows else None)

    async def reload(self, select_id: object = None) -> None:
        """Rebuild the list from the API, optionally re-selecting an account."""
        await self._load(select_id=select_id)

    async def _open_add_account(self) -> None:
        """Themed form to create a manual account (name, type, opening balance).
        Classification (asset/liability) is derived from the chosen type."""
        form = {"name": "", "balance": "0"}
        name = FormTextField(
            label="Account name",
            on_change=lambda e: form.__setitem__(
                "name", (getattr(e.control, "value", "") or "").strip()
            ),
            width=360,
        )
        type_dd = FormDropdown(
            label="Type",
            options=list(_ADD_ACCOUNT_TYPES),
            value="checking",
            width=360,
        )
        balance = FormTextField(
            label="Opening balance ($)",
            value="0",
            on_change=lambda e: form.__setitem__(
                "balance", getattr(e.control, "value", "") or ""
            ),
            width=360,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _add() -> None:
            account_name = form["name"].strip()
            if not account_name:
                ErrorSnackBar("Account name is required.").launch(self.page)
                return
            dialog.open = False
            self.page.update()
            account_type = type_dd.value or "checking"
            classification = (
                "liability" if account_type in _LIABILITY_ACCOUNT_TYPES else "asset"
            )
            await self._do_add_account(
                name=account_name,
                account_type=account_type,
                classification=classification,
                current_balance=_parse_dollars(form["balance"]),
            )

        dialog = StyledAlertDialog(
            title="Add account",
            body=ft.Column(
                [name, type_dd, balance],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_add,
                    text="Add account",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    async def _do_add_account(
        self,
        *,
        name: str,
        account_type: str,
        classification: str,
        current_balance: int,
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/accounts",
            json={
                "name": name,
                "account_type": account_type,
                "classification": classification,
                "current_balance": current_balance,
                "currency": "usd",
            },
        )
        if not isinstance(result, dict) or "id" not in result:
            ErrorSnackBar("Could not add the account.").launch(self.page)
            return
        SuccessSnackBar(f"Added {name}.").launch(self.page)
        await self.reload(select_id=result["id"])

    async def _connect_bank(self) -> None:
        await _connect_bank_flow(self.page, self.reload)

    async def _connect_brokerage(self) -> None:
        await _connect_brokerage_flow(self.page, self.reload)


def _account_detail_header(
    account: dict, *, on_rename, on_remove, on_reconcile
) -> ft.Control:
    """The header shown above an account's register: name, type, balance, and a
    Manage menu (Rename and Reconcile always; Remove for manual accounts only —
    provider accounts are owned by the bank connection)."""
    balance = _account_display_balance(account)
    is_manual = account.get("is_manual", False)
    classification = (account.get("classification") or "asset").title()
    source = "Manual" if is_manual else "Connected"
    meta = f"{classification}  ·  {source}  ·  {(account.get('currency') or 'usd').upper()}"

    menu_items = [
        ft.PopupMenuItem(text="Rename", on_click=lambda _e: on_rename(account)),
        ft.PopupMenuItem(text="Reconcile", on_click=lambda _e: on_reconcile(account)),
    ]
    if is_manual:
        menu_items.append(
            ft.PopupMenuItem(text="Remove", on_click=lambda _e: on_remove(account))
        )
    manage = ft.PopupMenuButton(
        icon=ft.Icons.MORE_VERT,
        # Explicit: without it the icon inherits the theme primary (teal),
        # and accent means "act on me" - a quiet overflow trigger isn't that.
        # Same ink as ActionMenu's kebab and every other muted icon button.
        icon_color=ft.Colors.ON_SURFACE_VARIANT,
        tooltip="Manage account",
        items=menu_items,
    )

    left = ft.Column(
        [
            ft.Row(
                [
                    ft.Text(
                        account.get("name", ""),
                        size=Theme.Typography.H3,
                        color=Theme.Colors.TEXT_PRIMARY,
                        weight=ft.FontWeight.W_600,
                    ),
                    Tag(
                        text=_type_label(account.get("account_type")),
                        color=Theme.Colors.INFO,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Text(
                meta,
                size=Theme.Typography.CAPTION,
                color=Theme.Colors.TEXT_SECONDARY,
            ),
        ],
        spacing=Theme.Spacing.XS,
        expand=True,
    )
    right = NumericText(
        _usd(balance),
        size=Theme.Typography.H2,
        color=headline_stat_color(balance),
        weight=ft.FontWeight.W_700,
    )
    return ft.Container(
        content=ft.Row(
            [left, right, manage],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.only(bottom=Theme.Spacing.SM),
    )


# Matches the Category DataTableColumn's own width below - see
# UncategorizedPanel's _CATEGORY_COLUMN_WIDTH for why the category cell
# needs an explicit width at all (category_trigger_cell relies on it).
_TXN_CATEGORY_COLUMN_WIDTH = 200


class TransactionsPanel(ft.Container):
    """Right-hand detail: the selected account's header + transactions (or
    holdings), with a payee search. ``All Accounts`` shows every transaction."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__()
        self.page = page
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        # The dialog-wide filter narrows ALL ACCOUNTS. It does not fight
        # the sidebar: picking one account there is a narrower choice and
        # wins, the same way a search box narrows within whatever is
        # already on screen.
        self._account_filter = account_filter or AccountFilter()
        if register_filter_listener is not None:
            register_filter_listener(self._on_account_filter_change)
        self._account: dict | None = None
        self._query = ""
        # Grows by a page each "Load more" (see _load_more) - accumulate
        # rather than paginate, so the merged trades lane stays coherent.
        self._register_page_size = _REGISTER_PAGE_SIZE
        # The register's one DataTable, fed via set_rows so the scroll
        # position survives every edit-triggered reload; rebuilt only
        # when the column set changes (account <-> All Accounts).
        self._register_table: DataTable | None = None
        self._register_scope: bool | None = None
        self._reload_accounts = None  # set by the owner; reloads the sidebar
        # no_wrap on both: these sit in the flex slot of a Row full of
        # fixed-width controls, so if that Row is ever over-subscribed
        # again they ellipsize instead of wrapping to one character per
        # line (confirmed live - the subtitle rendered as a vertical
        # column of single letters down the left edge).
        self._title = ft.Text(
            "All Accounts",
            size=Theme.Typography.H3,
            color=Theme.Colors.TEXT_PRIMARY,
            weight=ft.FontWeight.W_600,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._subtitle = ft.Text(
            "",
            size=Theme.Typography.BODY_SMALL,
            color=Theme.Colors.TEXT_SECONDARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        # Beside the count, not under the table: a footer permanently
        # costs one row's height, and the count line is the chrome that
        # already tells this story ("Showing 100 of 685").
        self._load_more_link = PulseButton(
            on_click_callable=self._load_more,
            text="Load more",
            variant="muted",
            compact=True,
        )
        self._load_more_link.visible = False
        self._debounce = Debouncer(page)
        self._search = FormTextField(
            label="Search payee",
            on_change=self._on_change,
            on_submit=self._on_submit,
            width=280,
            compact=True,
            clearable=True,
        )
        # Trailing-window filter - the SAME DateRangeChips control the
        # insights tabs use, so every range picker in the product is one
        # visual family. Defaults to 90 days so a deep historical import
        # does not render its full register on every open; "All" is the
        # insights convention of a huge sentinel window.
        self._range_days = 90
        self._range = DateRangeChips(
            options=[
                ("1d", 1),
                ("7d", 7),
                ("14d", 14),
                ("1m", 30),
                ("3m", 90),
                ("1y", 365),
                ("All", 9999),
            ],
            selected_days=self._range_days,
            on_change=self._on_range_change,
        )
        # Browser-side file pick + upload for the transaction-file import.
        # The picker must live in page.overlay to render; the modal (and so
        # this panel) is built once per session, so this appends once.
        self._file_picker = ft.FilePicker(
            on_result=self._on_import_picked, on_upload=self._on_import_progress
        )
        page.overlay.append(self._file_picker)
        # Server-side name of the upload in flight (uuid-prefixed); None
        # when no import is running. Doubles as the re-entry guard.
        self._pending_upload: str | None = None
        # Which Import menu item opened the picker; read by _finish_import
        # to route to the investment lane instead of the register
        # preview/commit flow.
        self._import_is_investment = False
        # Account-detail header (visible only when a specific account is chosen).
        self._detail = ft.Container(visible=False)
        self._body = ft.Container(expand=True)
        # Re-categorizing an already-categorized transaction ("fix what's
        # messed up"), not just filling an empty one - same shared
        # CategoryPickerButton/BulkCategorizeTrigger UncategorizedPanel
        # uses (pickers.py), one instance per panel per that
        # class's own docstring. Unlike Uncategorized there's no pending/
        # Save staging here: a pick applies immediately (apply_category_picks)
        # since this is a register you browse and correct, not a review
        # queue with a batch commit step.
        self._categories: list[tuple[str, str]] = []
        self._merchants: list[tuple[str, str]] = []
        self._selected_txn_ids: set[int] = set()
        self._selected_amount = 0  # cents, in step with the ids above
        self._selected_trade_count = 0
        # Resolved account names, for the Account column that only All
        # Accounts shows. Fetched once and kept - the list is small and
        # does not change while the modal is open.
        self._account_names: dict[int, str] = {}
        self._category_picker = CategoryPickerButton(
            categories=self._categories,
            on_pick=self._pick_category,
            on_create=self._create_category,
        )
        # The payee picker is what makes a bill survive a descriptor
        # change - see FinanceService's "payees (merchants)" section and
        # categorize/recurring.py's _payee_key.
        self._merchant_picker = MerchantPickerButton(
            merchants=self._merchants,
            on_pick=self._pick_merchant,
            on_create=self._create_merchant,
        )
        self._selection_label = SecondaryText("", visible=False)
        # The active tag filter (a tag dict), set by clicking a row's chip.
        # It narrows within whatever account/range/search is already on
        # screen, and clears from the chip beside the subtitle.
        self._tag_filter: dict | None = None
        self._tag_filter_chip = ft.Container(visible=False)
        self._tags: list[tuple[str, str]] = []
        # Pick and create land on the SAME handler: the server's attach is
        # get-or-create by name, so "choose Flagged" and "type Flagged"
        # are one operation with two spellings.
        self._tag_picker = TagPickerButton(
            tags=self._tags,
            on_pick=self._apply_tag,
            on_create=self._apply_tag,
        )
        self._bulk_categorize_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_categorize
        )
        self._bulk_payee_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_payee,
            label="Set payee",
            tooltip="Assign the same payee to every checked row at once",
        )
        self._bulk_recurring_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_recurring,
            label="Make recurring",
            tooltip=(
                "Turn the checked rows into a confirmed bill or income, "
                "and fold any duplicate of it into one"
            ),
        )
        self._bulk_tag_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_tag,
            label="Tag",
            tooltip=(
                "Put a tag on every checked row - flag things to follow "
                "up on, group a trip, mark tax items"
            ),
        )
        self._bulk_delete_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_delete,
            label="Delete",
            variant="stop",
            tooltip=(
                "Delete every checked row from the ledger. Deleted rows "
                "stay deleted - re-importing the same file will not bring "
                "them back"
            ),
        )
        # The selection controls live on their OWN row, appearing only
        # when something is checked. They were in the header row, which
        # already carried the title, seven range chips and the search box:
        # around 1,200px of fixed-width content. The title/subtitle Column
        # is the only flexible child there, so the moment three more chips
        # appeared it was squeezed to a few pixels and wrapped one
        # character per line down the side of the page.
        self._selection_row = ft.Container(
            content=ft.Row(
                [
                    self._selection_label,
                    self._bulk_payee_trigger,
                    self._bulk_categorize_trigger,
                    self._bulk_recurring_trigger,
                    self._bulk_tag_trigger,
                    self._bulk_delete_trigger,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=Theme.Spacing.MD,
            ),
            padding=ft.padding.symmetric(vertical=Theme.Spacing.SM),
            visible=False,
        )
        self.content = ft.Column(
            [
                self._detail,
                ft.Row(
                    [
                        ft.Column(
                            [
                                self._title,
                                ft.Row(
                                    [
                                        self._subtitle,
                                        self._tag_filter_chip,
                                        self._load_more_link,
                                    ],
                                    spacing=Theme.Spacing.SM,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        self._range,
                        self._search,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.MD,
                ),
                self._selection_row,
                ft.Container(height=Theme.Spacing.MD),
                self._body,
                # Zero-size mount points for the pickers' own overlays -
                # see SearchPickerButton's docstring.
                self._category_picker,
                self._merchant_picker,
                self._tag_picker,
            ],
            spacing=0,
            expand=True,
        )

    def set_reload_hook(self, reload_accounts) -> None:
        """Wire the sidebar's reload coroutine so management actions can refresh
        the account list after a rename/remove."""
        self._reload_accounts = reload_accounts

    def select(self, account: dict | None) -> None:
        self._account = account
        is_account = account is not None
        is_investment = is_account and account.get("account_type") in _INVESTMENT_TYPES
        # The detail header replaces the plain title when an account is chosen.
        self._detail.visible = is_account
        self._detail.content = (
            _account_detail_header(
                account,
                on_rename=self._open_rename,
                on_remove=self._open_remove,
                on_reconcile=self._open_reconcile,
            )
            if is_account
            else None
        )
        self._title.visible = not is_account
        self._title.value = "All Accounts"
        # Payee search only applies to the transaction view.
        self._search.visible = not is_investment
        self._subtitle.value = ""
        if self._detail.page is not None:
            self._detail.update()
            self._title.update()
            self._subtitle.update()
            self._search.update()
        self.page.run_task(self._load_holdings if is_investment else self._load)

    def _set_subtitle(
        self,
        count: int,
        shown_sum: int | None = None,
        filtered: bool = False,
        shown: int | None = None,
    ) -> None:
        """The register's summary line.

        ``count`` is whatever the CURRENT search and date range matched,
        so pairing it with the account's register balance states two
        different populations as one fact: searching "anthr" on a 5,552
        transaction account rendered "13 transactions - Register balance
        $1,200.12" when those 13 sum to -$2,158.19 and the $1,200.12
        belongs to all 5,552. While a filter is on, the line therefore
        gives the matched rows their OWN total and renames the balance to
        say whose it is.
        """
        parts = [register_count_label(shown, count)]
        if self._account is None:
            self._subtitle.value = "  ·  ".join(parts)
        else:
            balance = _account_display_balance(self._account)
            if filtered:
                parts = [register_count_label(shown, count, noun="matching")]
                # Only when the page holds every match - a partial page
                # would total a slice while looking like the whole.
                if shown_sum is not None:
                    parts.append(f"Total {_usd(shown_sum)}")
                parts.append(f"Account balance {_usd(balance)}")
            else:
                parts.append(f"Register balance {_usd(balance)}")
            self._subtitle.value = "  ·  ".join(parts)
        self._load_more_link.visible = shown is not None and shown < count
        if self._load_more_link.page is not None:
            self._load_more_link.update()
        if self._subtitle.page is not None:
            self._subtitle.update()

    def _on_account_filter_change(self) -> None:
        if self.page:
            self.page.run_task(self._load)

    def _on_change(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        # Type-ahead: the register re-filters on its own once typing
        # pauses, so Enter becomes optional rather than required.
        self._debounce.schedule(self._load)

    def _on_submit(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        self._debounce.run_now(self._load)

    def _range_from(self) -> date | None:
        if self._range_days >= 9000:  # the "All" sentinel, per insights
            return None
        return date.today() - timedelta(days=self._range_days)

    def _on_range_change(self, days: int) -> None:
        self._range_days = days
        is_investment = self._account is not None and (
            self._account.get("account_type") in _INVESTMENT_TYPES
        )
        self.page.run_task(self._load_holdings if is_investment else self._load)

    # -- File import (OFX/QFX/QIF/CSV, or a custodian ledger for a
    #    brokerage account) --------------------------------------------

    async def open_transactions_import_picker(self) -> None:
        """Open the browser file dialog for a register (bank/card) import.

        Public: the sidebar's Import menu, "Transactions" item.
        """
        await self._open_import_picker(investments=False)

    async def open_investments_import_picker(self) -> None:
        """Open the browser file dialog for an investment-ledger import.

        Public: the sidebar's Import menu, "Investments" item. No
        preconditions: the target account is chosen (or created) in the
        review dialog AFTER the file is parsed, the same order the
        register import works in - file first, decisions second.
        """
        await self._open_import_picker(investments=True)

    async def _open_import_picker(self, *, investments: bool) -> None:
        if self._pending_upload is not None:
            return  # an import is already in flight
        self._import_is_investment = investments
        if investments:
            self._file_picker.pick_files(
                dialog_title="Import investment activity",
                allow_multiple=False,
                allowed_extensions=["csv", "tsv", "txt"],
            )
        else:
            self._file_picker.pick_files(
                dialog_title="Import transactions",
                allow_multiple=False,
                allowed_extensions=["ofx", "qfx", "qif", "csv"],
            )

    def _on_import_picked(self, event: ft.FilePickerResultEvent) -> None:
        if not event.files:
            return  # dialog cancelled
        picked = event.files[0]
        name = picked.name or "upload"
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if (
            extension == "qif"
            and self._account is None
            and not self._import_is_investment
        ):
            # QIF carries no account info; fail before the round trip with
            # an instruction instead of a server 400 the client cannot read.
            ErrorSnackBar(
                "Select an account in the sidebar first. QIF files do not "
                "name their account."
            ).launch(self.page)
            return
        # Unique server-side name so concurrent sessions cannot collide
        # (uuid4().hex has no dashes, so split on the first dash recovers
        # the original file name later).
        self._pending_upload = f"{uuid4().hex}-{name}"
        upload_url = self._import_upload_url(self._pending_upload)
        # Block the page for the whole upload+import; cleared by
        # _finish_import (success) or fail() (any error).
        LoadingOverlay.of(self.page).show(f"Uploading {name}...")
        self._file_picker.upload([ft.FilePickerUploadFile(name, upload_url=upload_url)])

    def _import_upload_url(self, server_name: str) -> str:
        """Signed URL for the dashboard-mounted flet upload endpoint.

        ``page.get_upload_url`` cannot be used here: the Flet app is
        mounted at ``/dashboard``, so flet would sign its sub-app-relative
        endpoint while the server verifies the externally visible path
        (``request.url.path`` includes the mount prefix). Signing the
        external path directly satisfies both the route and the check.
        """
        from flet_web.uploads import build_upload_url

        return build_upload_url(
            "/dashboard/upload", server_name, 600, settings.SECRET_KEY
        )

    def _on_import_progress(self, event: ft.FilePickerUploadEvent) -> None:
        if event.error:
            self._pending_upload = None
            LoadingOverlay.of(self.page).fail(
                f"Upload failed: {event.error}", title="Import failed"
            )
            return
        if (event.progress or 0) >= 1.0:
            self.page.run_task(self._finish_import)

    async def _finish_import(self) -> None:
        """Hand the uploaded file to the import API, report, and refresh."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        pending, self._pending_upload = self._pending_upload, None
        if pending is None:
            return
        upload_path = dashboard_upload_dir() / pending
        try:
            data = upload_path.read_bytes()
        except OSError:
            overlay.fail(
                "Upload failed: file did not arrive on the server.",
                title="Import failed",
            )
            return
        finally:
            upload_path.unlink(missing_ok=True)

        original_name = pending.split("-", 1)[1]
        if self._import_is_investment:
            await self._finish_investment_import(data, original_name)
            return

        # Classify first, commit second. The preview endpoint runs the SAME
        # plan the import executes, so the review dialog shows exactly what
        # pressing Import will do - and until then nothing is written.
        overlay.update_label(f"Checking {original_name}...")
        params: dict[str, object] = {}
        if self._account is not None:
            params["account_id"] = self._account["id"]
        api = get_session_state(self.page).api_client
        preview = await api.post_multipart(
            "/api/v1/finance/import/preview",
            files={"file": (original_name, data, "application/octet-stream")},
            params=params,
        )
        if not isinstance(preview, dict):
            # Show the real reason (HTTP status + detail body), not a
            # guess - that is the whole point of the overlay.
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        overlay.hide()
        await self._show_import_preview(preview, data, original_name)

    async def _finish_investment_import(self, data: bytes, original_name: str) -> None:
        """Parse-preview the ledger, then open the review dialog where the
        target account is chosen (or created). Mirrors the register
        import's order - classify first, commit second - so nothing is
        written until the dialog's Import button."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        overlay.update_label(f"Checking {original_name}...")
        api = get_session_state(self.page).api_client
        preview = await api.post_multipart(
            "/api/v1/finance/import-investments/preview",
            files={"file": (original_name, data, "application/octet-stream")},
        )
        if not isinstance(preview, dict):
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        accounts = await api.get("/api/v1/finance/accounts")
        account_rows = accounts.get("items", []) if isinstance(accounts, dict) else []
        overlay.hide()
        await self._show_investment_import_review(
            preview, account_rows, data, original_name
        )

    async def _show_investment_import_review(
        self,
        preview: dict,
        accounts: list[dict],
        data: bytes,
        original_name: str,
    ) -> None:
        """The pre-commit review: what the ledger replays to, and where it
        goes - an existing investment account, or one created on the spot
        (the same courtesy OFX ingest extends to unknown accounts)."""
        selected_id = self._account.get("id") if self._account is not None else None
        options, default = investment_target_options(accounts, selected_id)
        name_field = FormTextField(
            label="New account name",
            value=_suggested_account_name(original_name),
        )
        name_host = ft.Container(
            content=name_field, visible=default == _NEW_ACCOUNT_KEY
        )

        def _target_changed(event: ft.ControlEvent) -> None:
            name_host.visible = event.control.value == _NEW_ACCOUNT_KEY
            if name_host.page is not None:
                name_host.update()

        target_dd = FormDropdown(
            label="Into account",
            options=options,
            value=default,
            on_change=_target_changed,
        )
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _commit() -> None:
            choice = target_dd.value or _NEW_ACCOUNT_KEY
            params: dict[str, object] = {}
            if choice == _NEW_ACCOUNT_KEY:
                name = (name_field.value or "").strip()
                if not name:
                    name_field.set_error("Name the new account.")
                    return
                params["account_name"] = name
            else:
                params["account_id"] = int(choice)
            await _close()
            await self._run_investment_import(data, original_name, params)

        dialog = StyledAlertDialog(
            title=f"Import {original_name}",
            body=ft.Column(
                [
                    investment_import_preview_body(preview),
                    ft.Container(height=Theme.Spacing.SM),
                    target_dd,
                    name_host,
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_commit,
                    text="Import",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=560,
        )
        self.page.open(dialog)

    async def _run_investment_import(
        self, data: bytes, original_name: str, params: dict[str, object]
    ) -> None:
        """Commit a reviewed ledger. Synchronous, no background job - a
        few hundred rows loads in well under a second, unlike a
        multi-year bank statement."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        overlay.show(f"Importing {original_name}...")
        api = get_session_state(self.page).api_client
        response = await api.post_multipart(
            "/api/v1/finance/import-investments",
            files={"file": (original_name, data, "application/octet-stream")},
            params=params,
        )
        if not isinstance(response, dict):
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        overlay.hide()
        await self._show_investment_import_summary(response)

        # The target may be a freshly minted account: refresh the sidebar
        # onto it, and this panel's own view if it's the one showing.
        target_id = response.get("account_id")
        if self._account is not None and self._account.get("id") == target_id:
            await self._load_holdings()
        if self._reload_accounts is not None:
            await self._reload_accounts(target_id)

    async def _show_investment_import_summary(self, response: dict) -> None:
        """Modal breakdown of an investment-ledger import; dismissed by OK."""
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        dialog = StyledAlertDialog(
            title="Import complete",
            body=investment_import_summary_body(response),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="OK",
                    variant="teal",
                    compact=True,
                )
            ],
            width=500,
        )
        self.page.open(dialog)

    async def _run_import(self, data: bytes, original_name: str) -> None:
        """Commit a previewed file: the background import job path."""
        from app.components.frontend.state.session_state import get_session_state

        overlay = LoadingOverlay.of(self.page)
        overlay.show(f"Importing {original_name}...")
        params: dict[str, object] = {"background": "true"}
        if self._account is not None:
            params["account_id"] = self._account["id"]
        else:
            params.update(self._account_filter.params())
        api = get_session_state(self.page).api_client
        # The endpoint validates the upload and returns a job id in
        # milliseconds; the long part (row inserts + reconciliation rules)
        # runs as a server job whose SSE stream drives this overlay. No
        # request is left holding a multi-minute connection.
        started = await api.post_multipart(
            "/api/v1/finance/import",
            files={"file": (original_name, data, "application/octet-stream")},
            params=params,
        )
        if not isinstance(started, dict) or "job_id" not in started:
            overlay.fail(
                api.last_error or "Import failed for an unknown reason.",
                title="Import failed",
            )
            return
        response = await overlay.run_job(api, started["job_id"], title="Import failed")
        if response is None:
            return  # run_job already showed the job's error

        overlay.hide()
        # An import moves real money around: the outcome gets a modal the
        # user has to acknowledge, not a snackbar that fades while they are
        # looking elsewhere. Every row is accounted for - the counts sum to
        # the file's row total, so nothing vanished silently.
        await self._show_import_summary(response)

        # Balances and the register both moved; refresh panel + sidebar.
        await self._load()
        if self._reload_accounts is not None:
            account_id = self._account["id"] if self._account is not None else None
            await self._reload_accounts(account_id)

    async def _show_import_preview(
        self, preview: dict, data: bytes, original_name: str
    ) -> None:
        """The pre-commit review: what this file will do, before it does it.

        Import commits the very bytes just previewed (the batch dedup ties
        the two requests together by file hash); Cancel writes nothing.
        """
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        if preview.get("identical_batch_id") is not None:
            dialog = StyledAlertDialog(
                title="Nothing to import",
                body=import_identical_body(preview, original_name),
                actions=[
                    PulseButton(
                        on_click_callable=_close,
                        text="OK",
                        variant="teal",
                        compact=True,
                    )
                ],
                width=520,
            )
            self.page.open(dialog)
            return

        inserted = preview.get("rows_inserted", 0)
        updated = preview.get("rows_updated", 0)
        body = import_preview_body(preview, original_name)

        async def _confirm() -> None:
            await _close()
            await self._run_import(data, original_name)

        changes = inserted + updated
        plural_changes = "s" if changes != 1 else ""
        import_label = (
            f"Import {changes:,} change{plural_changes}" if changes else "Import"
        )
        dialog = StyledAlertDialog(
            title="Review import",
            body=body,
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_confirm,
                    text=import_label,
                    variant="teal",
                    compact=True,
                ),
            ],
            # Three metric cards need the room; 640 squeezed "Already have"
            # onto two lines.
            width=700,
        )
        self.page.open(dialog)

    async def _show_import_summary(self, response: dict) -> None:
        """Modal breakdown of an import; dismissed by OK."""
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        dialog = StyledAlertDialog(
            title="Import complete",
            body=import_summary_body(response),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="OK",
                    variant="teal",
                    compact=True,
                )
            ],
            # Matches the review dialog it echoes: same three cards, so
            # the same room, so the two screens line up.
            width=700,
        )
        self.page.open(dialog)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        # Claim this run. Two requests in flight can return out of order,
        # so a superseded one must not paint - otherwise the register can
        # settle on results for a prefix of what was typed.
        sequence = self._debounce.sequence
        api = get_session_state(self.page).api_client
        # A fresh table build below has nothing checked - a stale
        # self._selected_txn_ids from before this load (a different
        # account, a different search) would otherwise leave the bulk
        # trigger showing a count for rows that no longer exist on screen.
        self._selected_txn_ids = set()
        self._selected_amount = 0
        self._selected_trade_count = 0
        self._update_selection_label()
        if not self._categories:
            from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

            cat_data = await api.get("/api/v1/finance/categories/options")
            cat_items = cat_data.get("items", []) if isinstance(cat_data, dict) else []
            self._categories = [
                (str(c["id"]), c["name"])
                for c in cat_items
                if str(c.get("name", "")).lower() not in UNCATEGORIZED_CATEGORY_NAMES
            ]
            self._category_picker.update_categories(self._categories)
        await self._reload_merchants(api)
        await self._reload_tags(api)
        if not self._account_names:
            accounts = await api.get(
                "/api/v1/finance/accounts", params={"page_size": 200}
            )
            self._account_names = {
                a["id"]: a.get("name", "Account")
                for a in (
                    accounts.get("items", []) if isinstance(accounts, dict) else []
                )
            }
        params: dict[str, object] = {"page_size": self._register_page_size}
        from_date = self._range_from()
        if from_date is not None:
            params["from"] = from_date.isoformat()
        if self._account is not None:
            params["account_id"] = self._account["id"]
        else:
            # The account picker scopes All Accounts too. It never did -
            # the fetch carried no account scope at all, so "2 of 15
            # accounts" changed nothing here and a checked account's rows
            # could still sit past the page edge (confirmed live). An
            # explicit empty selection means literally nothing, same as
            # every other consumer of AccountFilter.params().
            if self._account_filter.is_empty:
                self._body.content = EmptyStatePlaceholder(
                    message="No accounts selected."
                )
                self._refresh()
                return
            params.update(self._account_filter.params())
        if self._query:
            params["q"] = self._query
        if self._tag_filter is not None:
            params["tag_id"] = self._tag_filter["id"]
        data = await api.get("/api/v1/finance/transactions", params=params)
        if not self._debounce.is_current(sequence):
            return  # a newer keystroke already owns the register
        items = data.get("items", []) if isinstance(data, dict) else []
        total = data.get("total", len(items)) if isinstance(data, dict) else len(items)

        # All Accounts also folds in investment activity: brokerage accounts
        # ledger trades, not transactions, so a trades-only stack would
        # otherwise render an empty register.
        trades: list[dict] = []
        if self._account is None:
            # Same scope as the transactions fetch - without it every
            # brokerage's trades rode along whatever the picker said.
            activity = await api.get(
                "/api/v1/finance/trades", params=self._account_filter.params()
            )
            trades = activity.get("items", []) if isinstance(activity, dict) else []
            if from_date is not None:
                cutoff = from_date.isoformat()
                trades = [t for t in trades if str(t.get("trade_date", "")) >= cutoff]
            if self._query:
                q = self._query.lower()
                trades = [t for t in trades if q in (t.get("name") or "").lower()]
            total += len(trades)
            # Hold trades below the transaction page's edge for Load more
            # (see trades_within_page) - they still COUNT above, so the
            # subtitle's "of" covers both lanes in full.
            trades = trades_within_page(
                trades,
                oldest_txn_date=str(items[-1].get("date")) if items else None,
                page_complete=len(items) >= total - len(trades),
            )

        # Trades ride along only in All Accounts, which has no register
        # balance line to contradict - so the matched total is computed
        # for a selected account, where the confusion actually lives.
        filtered = bool(self._query) or from_date is not None
        shown_sum: int | None = None
        if filtered and self._account is not None and len(items) == total:
            shown_sum = sum(int(i.get("amount") or 0) for i in items)
        self._set_subtitle(
            total,
            shown_sum=shown_sum,
            filtered=filtered,
            shown=len(items) + len(trades),
        )
        if not items and not trades:
            self._body.content = EmptyStatePlaceholder(
                message="No transactions for this account."
            )
            self._refresh()
            return

        merged: list[tuple[str, dict]] = [("txn", t) for t in items] + [
            ("trade", t) for t in trades
        ]
        merged.sort(
            key=lambda pair: str(pair[1].get("date") or pair[1].get("trade_date")),
            reverse=True,
        )

        all_accounts = self._account is None
        columns = register_columns(all_accounts)

        def _category_cell(record: dict) -> ft.Control:
            # Re-categorizing an ALREADY-categorized transaction - unlike
            # UncategorizedPanel's placeholder, this shows the current
            # pick as the trigger's own label, same idea as any other
            # "click a value to change it" field.
            txn_id = record.get("id")
            label = TableCellText(record.get("category") or "Uncategorized")
            if txn_id is None:
                return label
            return picker_trigger_cell(
                label,
                _TXN_CATEGORY_COLUMN_WIDTH,
                on_tap=lambda e, t=txn_id: self._category_picker.open_for([t], e),
                tooltip="Click to change category",
            )

        def _payee_cell(record: dict) -> ft.Control:
            # Shows the assigned PAYEE when there is one, falling back to
            # the raw bank descriptor - Quicken's behavior, and the reason
            # the descriptor isn't lost either way is that the row's
            # inline-expand detail still lists "Original description".
            # Assigning here is what makes a bill survive the descriptor
            # changing later (categorize/recurring.py's _payee_key).
            txn_id = record.get("id")
            payee = record.get("merchant")
            raw = record.get("name") or ""
            if txn_id is None:
                return TableNameText(raw)
            cell = picker_trigger_cell(
                ft.Row(
                    [
                        ProviderIcon(payee or raw, record.get("icon_b64")),
                        ft.Container(content=TableNameText(payee or raw), expand=True),
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                None,
                on_tap=lambda e, t=txn_id: self._merchant_picker.open_for([t], e),
                tooltip=(
                    f"Payee: {payee}\n{raw}\nClick to change"
                    if payee
                    else "No payee assigned - click to set one"
                ),
            )
            # DataTable sorts a control cell by its .data (see
            # data_table.py's _cell_text) - a Row has no .value of its
            # own, so Payee would silently stop sorting without this.
            cell.data = payee or raw
            return cell

        def _account_cell(record: dict) -> list[ft.Control]:
            if not all_accounts:
                return []
            return [
                TableCellText(
                    self._account_names.get(record.get("account_id"), "\u2014")
                )
            ]

        def _tags_cell(record: dict) -> ft.Control:
            tags = record.get("tags") or []
            if not tags:
                cell = ft.Container(content=TableCellText(""))
                cell.data = ""
                return cell
            cell = ft.Row(
                transaction_tag_chips(
                    tags, on_tap=self._filter_by_tag, cap=2, compact=True
                ),
                spacing=Theme.Spacing.XS,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            # A Row has no .value, so the Tags column would silently stop
            # sorting without this (same note as the payee cell).
            cell.data = ", ".join(t.get("name", "") for t in tags)
            return cell

        def _row(kind: str, record: dict) -> list[ft.Control]:
            if kind == "trade":
                return [
                    date_cell(record.get("trade_date")),
                    *_account_cell(record),
                    TableNameText(
                        record.get("name") or _trade_type_label(record.get("type"))
                    ),
                    # Trades are not categorized - they are position moves,
                    # not spending.
                    TableCellText("\u2014"),
                    _tags_cell(record),
                    TableCellText(_trade_type_label(record.get("type")).lower()),
                    _amount_cell(record.get("amount", 0)),
                ]
            return [
                date_cell(record.get("date")),
                *_account_cell(record),
                _payee_cell(record),
                _category_cell(record),
                _tags_cell(record),
                TableCellText(record.get("source", "")),
                _amount_cell(
                    record.get("amount", 0),
                    excluded=bool(record.get("excluded_from_reports")),
                ),
            ]

        rows = [_row(kind, record) for kind, record in merged]

        def _expand(index: int, _merged: list = merged) -> ft.Control:
            kind, record = _merged[index]
            if kind == "trade":
                return _trade_expanded_content(record)
            return _transaction_expanded_content(record, on_remove_tag=self._remove_tag)

        def _on_selection_change(indices: set[int], _merged: list = merged) -> None:
            # Trades select like anything else, but they carry no payee or
            # category COLUMNS (FinanceTrade has neither), so the bulk
            # actions can only ever apply to the transactions in the
            # selection. The label says so - the one unforgivable version
            # is the old one, where a checked trade counted for nothing
            # and nothing said why.
            ids = set()
            amount = 0
            trades = 0
            for i in indices:
                if i < len(_merged):
                    kind, record = _merged[i]
                    if kind == "txn" and record.get("id") is not None:
                        ids.add(record["id"])
                        amount += int(record.get("amount") or 0)
                    elif kind == "trade":
                        trades += 1
            self._selected_txn_ids = ids
            self._selected_amount = amount
            self._selected_trade_count = trades
            self._update_selection_label()

        # ``expand=True`` puts the rows in a virtualized ListView filling the
        # panel (header + search stay pinned above): only visible rows render,
        # which is what keeps a 400-row register from freezing the modal.
        # Hover a row for a summary; click it to expand its detail inline.
        # ONE table for the register's lifetime (per column set): an edit
        # reloads the DATA, and rebuilding the table with it snapped the
        # scroll back to the top on every categorize (the whole reason
        # DataTable.set_rows exists). The closures above capture this
        # load's rows, so they ride along with the data they describe.
        if self._register_table is not None and self._register_scope == all_accounts:
            self._register_table.set_rows(
                rows,
                expandable_content=_expand,
                on_selection_change=_on_selection_change,
            )
        else:
            self._register_table = DataTable(
                columns=columns,
                rows=rows,
                row_padding=6,
                item_extent=_DENSE_ROW_HEIGHT,
                empty_message="No transactions",
                expandable_content=_expand,
                selectable=True,
                on_selection_change=_on_selection_change,
                column_picker=True,
                expand=True,
            )
            self._register_scope = all_accounts
        if self._body.content is not self._register_table:
            self._body.content = self._register_table
        self._refresh()

    async def _load_more(self) -> None:
        """Widen the page and refetch - the register accumulates rather
        than paginates, so sort order and the merged trades lane stay
        coherent with one code path."""
        self._register_page_size += _REGISTER_PAGE_SIZE
        await self._load()

    def _update_selection_label(self) -> None:
        count = len(self._selected_txn_ids)
        trades = getattr(self, "_selected_trade_count", 0)
        if count and trades:
            label = (
                f"{count} selected  ·  {_usd(self._selected_amount)}  ·  "
                f"{trades} trade{'s' if trades != 1 else ''} (no payee/category "
                "to set)"
            )
        elif count:
            label = f"{count} selected  ·  {_usd(self._selected_amount)}"
        elif trades:
            # Trades-only: the actions stay hidden, and this line is WHY -
            # a trade has no payee or category column to write to.
            label = (
                f"{trades} trade{'s' if trades != 1 else ''} selected  ·  "
                "trades carry no payee or category"
            )
        else:
            label = ""
        self._selection_label.value = label
        self._selection_label.visible = bool(count or trades)
        if self._selection_label.page:
            self._selection_label.update()
        self._bulk_categorize_trigger.set_count(count)
        self._bulk_payee_trigger.set_count(count)
        self._bulk_recurring_trigger.set_count(count)
        self._bulk_tag_trigger.set_count(count)
        self._bulk_delete_trigger.set_count(count)
        # The row reserves no height when empty, so the table does not
        # shift down by a blank strip while nothing is selected.
        self._selection_row.visible = bool(count or trades)
        if self._selection_row.page is not None:
            self._selection_row.update()
        elif self.page is not None:
            # A control that has never been shown may not be mounted, so
            # it has no .page of its own to update through - and the
            # update is silently skipped, leaving the buttons hidden no
            # matter how many rows are checked. Repaint the panel that
            # DOES have one. (These used to be direct children of an
            # always-visible Row, which is why the guard was safe before
            # they moved into a hidden one.)
            self.update()

    def _open_bulk_categorize(self, e: ft.ControlEvent) -> None:
        if self._selected_txn_ids:
            self._category_picker.open_for(list(self._selected_txn_ids), e)

    def _open_bulk_payee(self, e: ft.ControlEvent) -> None:
        if self._selected_txn_ids:
            self._merchant_picker.open_for(list(self._selected_txn_ids), e)

    def _open_bulk_recurring(self, _e: ft.ControlEvent) -> None:
        if self._selected_txn_ids and self.page is not None:
            self.page.run_task(self._preview_recurring, list(self._selected_txn_ids))

    # -- tags ------------------------------------------------------------

    def _open_bulk_tag(self, e: ft.ControlEvent) -> None:
        if self._selected_txn_ids:
            self._tag_picker.open_for(list(self._selected_txn_ids), e)

    def _open_bulk_delete(self, _e: ft.ControlEvent) -> None:
        if not self._selected_txn_ids or self.page is None:
            return
        ids = list(self._selected_txn_ids)
        count = len(ids)
        ConfirmDialog(
            self.page,
            title=f"Delete {count} transaction{'s' if count != 1 else ''}?",
            message=(
                f"{count} row{'s' if count != 1 else ''} totalling "
                f"{_usd(self._selected_amount)} will leave the register, "
                "budgets, and projections. Re-importing the same file "
                "will not bring them back."
            ),
            confirm_text="Delete",
            destructive=True,
            on_confirm=lambda: self._delete_transactions(ids),
        ).show()

    async def _delete_transactions(self, transaction_ids: list[int]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/transactions/delete",
            json={"transaction_ids": transaction_ids},
        )
        deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
        if not deleted:
            ErrorSnackBar("Could not delete those transactions.").launch(self.page)
            return
        SuccessSnackBar(
            f"Deleted {deleted} transaction{'s' if deleted != 1 else ''}."
        ).launch(self.page)
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        await self._load()

    async def _reload_tags(self, api) -> None:
        self._tags = await fetch_tag_options(api)
        self._tag_picker.update_tags(self._tags)

    def _apply_tag(self, transaction_ids: list[int], name: str) -> None:
        """TagPickerButton's on_pick AND on_create - same server verb."""
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_tag_async, transaction_ids, name.strip())

    async def _apply_tag_async(self, transaction_ids: list[int], name: str) -> None:
        if await post_tag(self.page, transaction_ids, name):
            await self._load()

    def _filter_by_tag(self, tag: dict) -> None:
        """A row chip was clicked: narrow the register to that tag."""
        if self.page is None:
            return
        self._tag_filter = tag
        self._render_tag_filter_chip()
        self.page.run_task(self._load)

    def _clear_tag_filter(self, _e: ft.ControlEvent) -> None:
        if self.page is None:
            return
        self._tag_filter = None
        self._render_tag_filter_chip()
        self.page.run_task(self._load)

    def _render_tag_filter_chip(self) -> None:
        """The active-filter chip beside the subtitle - the register never
        silently narrows; whatever is filtering it is on screen with an x."""
        active = self._tag_filter
        self._tag_filter_chip.visible = active is not None
        self._tag_filter_chip.content = (
            transaction_tag_chips(
                [active],
                on_remove=lambda _t: self._clear_tag_filter(None),
                remove_tooltip="Stop filtering by this tag",
            )[0]
            if active is not None
            else None
        )
        if self._tag_filter_chip.page is not None:
            self._tag_filter_chip.update()

    def _remove_tag(self, txn: dict, tag: dict) -> None:
        """The expanded row's chip x - detach one tag from one row."""
        if self.page is None:
            return
        self.page.run_task(self._remove_tag_async, txn, tag)

    async def _remove_tag_async(self, txn: dict, tag: dict) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/transactions/{txn['id']}/tags/{tag['id']}")
        await self._load()

    async def _preview_recurring(self, transaction_ids: list[int]) -> None:
        """Ask the server what this would do, then show it.

        A preview round trip rather than a plain "are you sure": the write
        is not confined to the rows that were ticked (it sweeps in every
        sibling of the same payee and folds away whatever already described
        the bill), and neither of those is guessable from the selection.
        """
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        plan = await api.post(
            "/api/v1/finance/transactions/declare-recurring/preview",
            json={"transaction_ids": transaction_ids},
        )
        groups = plan.get("items", []) if isinstance(plan, dict) else []
        if not groups:
            ErrorSnackBar(
                "Nothing to make recurring. Transfers and pending rows cannot be bills."
            ).launch(self.page)
            return
        self._open_recurring_dialog(transaction_ids, groups)

    def _open_recurring_dialog(
        self, transaction_ids: list[int], groups: list[dict]
    ) -> None:
        name_fields: dict[str, FormTextField] = {}
        amount_fields: dict[str, FormTextField] = {}
        category_fields: dict[str, CategoryPickerField] = {}
        frequency_fields: dict[str, FormDropdown] = {}
        # Rows unticked in the member tables, accumulated across groups.
        # Starts empty: everything the sweep found is in the bill until
        # the user says otherwise.
        excluded: set[int] = set()
        sections: list[ft.Control] = []
        for group in groups:
            key = group.get("key", "")
            members = group.get("members", [])
            rolled = group.get("occurrence_count", 0)
            picked = group.get("selected_count", 0)
            # 320 + 140 + 260 + two MD gaps fits inside the 820 dialog's
            # padded content; the old 360/140/300 row clipped its last
            # field at the dialog edge.
            field = FormTextField(
                label="Bill name",
                value=group.get("name", ""),
                width=320,
            )
            name_fields[key] = field
            # Prefilled from what you TICKED, not the sweep's median: one
            # bank descriptor can cover $500 and $16,320, and only the row
            # you picked is a figure you can vouch for. Stating it pins
            # the bill fixed-amount instead of "varies".
            amount_field = FormTextField(
                label="Amount ($)",
                value=f"{(group.get('selected_amount') or 0) / 100:.2f}",
                width=140,
            )
            amount_fields[key] = amount_field
            # The bill's category, set at the same time as its name. On
            # the STREAM only - the transactions rolling in keep theirs.
            category_dd = CategoryPickerField(
                categories=self._categories,
                width=260,
            )
            category_fields[key] = category_dd
            # The cadence, because measuring it only works for the six
            # canonical gaps detection knows. A semiannual premium is not
            # one of them: it measures as "irregular", which the forecast
            # cannot step, so the bill never reaches the projection at all.
            #
            # The default KEEPS whatever was measured (empty value, sent as
            # nothing), because ``FormDropdown`` falls back to its first
            # option otherwise - silently declaring a yearly premium weekly
            # is a worse failure than leaving it as it was.
            measured = group.get("frequency", "")
            keep_label = _frequency_label(measured)
            if measured not in _FREQUENCY_LABELS:
                keep_label += " (will not forecast)"
            frequency_dd = FormDropdown(
                label="Frequency",
                options=[("", keep_label), *_FREQUENCY_LABELS.items()],
                value="",
                width=200,
            )
            frequency_fields[key] = frequency_dd
            # What the cadence maths concluded, in the same line as the
            # roll-up count: those two together are the claim being made.
            facts = [
                _frequency_label(group.get("frequency", "")),
                _usd(-group.get("average_amount", 0))
                if group.get("direction") == "outflow"
                else _usd(group.get("average_amount", 0)),
            ]
            if group.get("amount_is_variable"):
                facts.append("amount varies")
            if group.get("next_expected_date"):
                facts.append(f"next {format_date(group['next_expected_date'])}")
            if group.get("account_name"):
                facts.append(str(group["account_name"]))
            # Wraps: four fields do not fit the 820 panel's padded width,
            # so name/amount/frequency take the first line and category
            # the second rather than the last field clipping at the edge.
            sections.append(
                ft.Row(
                    [field, amount_field, frequency_dd, category_dd],
                    spacing=Theme.Spacing.MD,
                    run_spacing=Theme.Spacing.SM,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                )
            )
            sections.append(SecondaryText("  ·  ".join(f for f in facts if f)))
            # The sweep, stated plainly. "13 transactions roll up (you
            # picked 2)" is the surprise worth naming before it happens.
            summary = f"{rolled:,} transaction{'s' if rolled != 1 else ''} roll up"
            if picked and picked != rolled:
                summary += f" (you picked {picked:,})"
            absorbs = group.get("absorbs") or []
            if absorbs:
                summary += f". Folds in: {', '.join(absorbs)}"
            sections.append(SecondaryText(summary))
            # A payee that really does sell you two things gets two bills.
            # Worth saying out loud, because the alternative reading - that
            # this is about to overwrite the bill already there - is the
            # scarier one.
            if group.get("creates_new_bill"):
                sections.append(
                    SecondaryText(
                        "Separate bill. "
                        f"{group.get('existing_bill_name') or 'An existing bill'} "
                        "keeps its own transactions.",
                        color=Theme.Colors.ACCENT,
                    )
                )
            sections.append(
                SecondaryText("Untick anything that is not part of this bill.")
            )

            def _on_member_toggle(indices: set[int], _members: list = members) -> None:
                # Inverted on purpose: the table reports what is CHECKED,
                # and this dialog cares about what is not.
                for position, member in enumerate(_members):
                    member_id = member.get("id")
                    if member_id is None:
                        continue
                    if position in indices:
                        excluded.discard(member_id)
                    else:
                        excluded.add(member_id)

            sections.append(
                DataTable(
                    columns=[
                        DataTableColumn("Date", width=120),
                        DataTableColumn("Description", hideable=False),
                        DataTableColumn("Amount", width=120, alignment="right"),
                    ],
                    rows=[
                        [
                            date_cell(m.get("date")),
                            TableNameText(m.get("name", "")),
                            _amount_cell(m.get("amount", 0)),
                        ]
                        for m in members
                    ],
                    row_padding=6,
                    item_extent=_DENSE_ROW_HEIGHT,
                    scroll_height=_group_table_height(
                        len(members),
                        getattr(self.page, "height", None),
                        tables=len(groups),
                        table_chrome=_DECLARE_GROUP_CHROME,
                    ),
                    selectable=True,
                    selected_indices=list(range(len(members))),
                    on_selection_change=_on_member_toggle,
                )
            )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        async def _confirm() -> None:
            names = {
                key: (field.value or "").strip()
                for key, field in name_fields.items()
                if (field.value or "").strip()
            }
            if len(names) != len(name_fields):
                ErrorSnackBar("Give every bill a name.").launch(self.page)
                return
            picked = {
                key: int(control.value)
                for key, control in category_fields.items()
                if control.value
            }
            stated = {
                key: cents
                for key, control in amount_fields.items()
                if (cents := _parse_dollars(control.value or "")) > 0
            }
            # Empty means "keep what was measured", so it is not sent.
            cadences = {
                key: control.value
                for key, control in frequency_fields.items()
                if control.value
            }
            dialog.open = False
            self.page.update()
            await self._declare_recurring(
                transaction_ids, names, sorted(excluded), picked, stated, cadences
            )

        total = sum(g.get("occurrence_count", 0) for g in groups)
        dialog = StyledAlertDialog(
            title="Make recurring" if len(groups) == 1 else "Make recurring bills",
            body=ft.Container(
                content=ft.Column(
                    sections,
                    spacing=Theme.Spacing.SM,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                height=_declare_body_height(
                    len(groups),
                    _group_table_height(
                        max((len(g.get("members") or []) for g in groups), default=0),
                        getattr(self.page, "height", None),
                        tables=len(groups),
                        table_chrome=_DECLARE_GROUP_CHROME,
                    ),
                    getattr(self.page, "height", None),
                ),
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_confirm,
                    text=f"Make recurring ({total:,})",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=820,
        )
        self.page.open(dialog)

    async def _declare_recurring(
        self,
        transaction_ids: list[int],
        names: dict[str, str],
        exclude_transaction_ids: list[int] | None = None,
        categories: dict[str, int] | None = None,
        amounts: dict[str, int] | None = None,
        frequencies: dict[str, str] | None = None,
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/transactions/declare-recurring",
            json={
                "transaction_ids": transaction_ids,
                "names": names,
                "exclude_transaction_ids": exclude_transaction_ids or [],
                "categories": categories or {},
                "amounts": amounts or {},
                "frequencies": frequencies or {},
            },
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not make that recurring.").launch(self.page)
            return
        streams = result.get("streams", 0)
        matched = result.get("transactions", 0)
        reconciled = result.get("reconciled", 0)
        if not streams:
            ErrorSnackBar(
                "Nothing to make recurring. Transfers and pending rows cannot be bills."
            ).launch(self.page)
            return
        message = (
            f"{streams} recurring "
            f"{'stream' if streams == 1 else 'streams'} from "
            f"{matched} transaction{'s' if matched != 1 else ''}."
        )
        if reconciled:
            message += (
                f" Folded in {reconciled} duplicate{'s' if reconciled != 1 else ''}."
            )
        SuccessSnackBar(message).launch(self.page)
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        await self._load()

    def _pick_category(self, transaction_ids: list[int], category_key: str) -> None:
        """CategoryPickerButton's on_pick contract - a single row's pick
        and a bulk "recategorize the selected rows" pick both land here,
        just with a longer list. Applies immediately (no pending/Save
        staging - see the constructor comment on why)."""
        if not category_key or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_category, transaction_ids, int(category_key))

    def _create_category(self, transaction_ids: list[int], name: str) -> None:
        """CategoryPickerButton's on_create contract: name a category that
        does not exist, then use it on the rows that needed it."""
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._create_and_apply, transaction_ids, name)

    async def _create_and_apply(self, transaction_ids: list[int], name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await create_category(api, name)
        if created is None:
            ErrorSnackBar("Could not create that category.").launch(self.page)
            return
        key, stored = created
        # Straight into the list so the picker has it without a reload,
        # and re-sorted because the picker shows them in order.
        if key not in {k for k, _ in self._categories}:
            self._categories = sorted(
                [*self._categories, (key, stored)], key=lambda c: c[1].casefold()
            )
            self._category_picker.update_categories(self._categories)
        await self._apply_category(transaction_ids, int(key))

    async def _apply_category(
        self, transaction_ids: list[int], category_id: int
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        saved_ids = await apply_category_picks(
            api, [(t, category_id) for t in transaction_ids]
        )
        failed = len(transaction_ids) - len(saved_ids)
        message = (
            f"Recategorized {len(saved_ids)}."
            if not failed
            else f"Recategorized {len(saved_ids)}, {failed} failed."
        )
        (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        await self._load()

    # -- payee assignment ----------------------------------------------------

    async def _reload_merchants(self, api) -> None:
        data = await api.get("/api/v1/finance/merchants")
        items = data.get("items", []) if isinstance(data, dict) else []
        self._merchants = [(str(m["id"]), m["name"]) for m in items]
        self._merchant_picker.update_merchants(self._merchants)

    def _pick_merchant(self, transaction_ids: list[int], merchant_key: str) -> None:
        """MerchantPickerButton's on_pick - an existing payee was chosen."""
        if not merchant_key or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_merchant, transaction_ids, int(merchant_key))

    def _create_merchant(self, transaction_ids: list[int], name: str) -> None:
        """MerchantPickerButton's on_create - a payee named inline."""
        if not name or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._create_and_apply_merchant, transaction_ids, name)

    async def _create_and_apply_merchant(
        self, transaction_ids: list[int], name: str
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await api.post("/api/v1/finance/merchants", json={"name": name})
        if not isinstance(created, dict) or created.get("id") is None:
            ErrorSnackBar(f'Could not create the payee "{name}".').launch(self.page)
            return
        await self._reload_merchants(api)
        await self._apply_merchant(transaction_ids, int(created["id"]))

    async def _apply_merchant(
        self, transaction_ids: list[int], merchant_id: int
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/transactions/assign-merchant",
            json={"transaction_ids": transaction_ids, "merchant_id": merchant_id},
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not set the payee.").launch(self.page)
            return
        updated = result.get("updated", 0)
        SuccessSnackBar(
            f"Payee set on {updated} transaction{'s' if updated != 1 else ''}."
        ).launch(self.page)
        # Only sweep for lookalikes after a SINGLE row: following a bulk
        # assign the user has already said which rows they meant, and
        # re-asking about lookalikes on top of an explicit selection is
        # second-guessing it. The category offer applies either way.
        similar = []
        if len(transaction_ids) == 1:
            data = await api.get(
                f"/api/v1/finance/transactions/{transaction_ids[0]}/similar"
            )
            similar = data.get("items", []) if isinstance(data, dict) else []
        summary = await api.get(
            f"/api/v1/finance/merchants/{merchant_id}/category-summary"
        )
        summary = summary if isinstance(summary, dict) else {}
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        if similar or self._category_offer_worth_making(summary):
            await self._offer_followup(api, merchant_id, similar, summary)
        await self._load()

    def _category_name_for(self, category_id: int | None) -> str | None:
        if category_id is None:
            return None
        key = str(category_id)
        return next((name for k, name in self._categories if k == key), None)

    @staticmethod
    def _category_offer_worth_making(summary: dict) -> bool:
        """Only ask when there's something to settle: the payee's own
        transactions disagree with each other, or some aren't categorized
        at all. A payee whose history already agrees (Google: 21 of 21
        "Bills & Utilities:Streaming") needs no dialog - silently
        re-confirming what's already true is just a click to dismiss."""
        total = summary.get("total", 0)
        if not total:
            return False
        return (
            summary.get("distinct_categories", 0) > 1
            or summary.get("dominant_count", 0) < total
        )

    async def _offer_followup(
        self, api, merchant_id: int, similar: list, summary: dict
    ) -> None:
        """One follow-up after naming a payee, covering both halves of
        "make this stick": the lookalike rows that should carry the same
        payee, and the category they should all share.

        Both are offers, never silent writes - the lookalike match is a
        loose heuristic (FinanceService.similar_unassigned) and the
        category is a judgement only the user can make, which is the same
        reason ``suggest_categories`` computes without applying. One
        dialog rather than two: they're a single decision about one payee,
        and asking twice in a row for one click is worse than asking once.
        """
        items = list(similar)

        # A real DataTable, not a formatted string: the same columns and
        # density as every other transaction list here, so the rows are
        # scannable (and ALL of them are shown, scrolling if need be,
        # rather than the first handful plus "and N more" - the whole
        # point of showing the list is that the match is a heuristic worth
        # checking). Checkboxes start all-on: a wrong lookalike gets
        # unticked rather than forcing all-or-nothing on the whole sweep.
        selected: set[int] = set(range(len(items)))
        columns = [
            DataTableColumn("Date", width=110),
            DataTableColumn("Payee", hideable=False),
            DataTableColumn("Amount", width=130, alignment="right"),
        ]
        rows = [
            [
                date_cell(i.get("date")),
                TableNameText(i.get("name") or ""),
                _amount_cell(i.get("amount", 0)),
            ]
            for i in items
        ]
        apply_button = PulseButton(
            on_click_callable=lambda: _apply_all(),
            text="Apply",
            variant="teal",
            compact=True,
        )

        # -- the category half -------------------------------------------
        # Pre-filled with whatever this payee's own transactions already
        # mostly use, so the common case is one glance and Apply. Ticked by
        # default only because we only get here when something disagrees
        # (see _category_offer_worth_making) - untick and no category is
        # written at all.
        offer_category = self._category_offer_worth_making(summary)
        preselected = summary.get("dominant_category_id") or summary.get(
            "default_category_id"
        )
        category_checkbox = ft.Checkbox(value=True, scale=0.85)
        # A NATIVE searchable dropdown, not this panel's CategoryPickerButton:
        # that one is a page.overlay popup, and a page.overlay popup nested
        # inside a real ft.AlertDialog renders BEHIND it (the exact layering
        # problem OverlayStyledDialog exists for - see base_popup.py). Flet's
        # own Dropdown is a Flutter menu, so it paints above the dialog, and
        # its enable_search covers the 267-category list. The custom picker
        # is still the right call in a table CELL, where this one was far
        # too cramped; a dialog has the room.
        category_dd = ft.Dropdown(
            options=[ft.dropdown.Option(key=k, text=t) for k, t in self._categories],
            value=str(preselected) if preselected else None,
            enable_filter=True,
            enable_search=True,
            dense=True,
            width=300,
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=6),
            menu_height=260,
        )

        total = summary.get("total", 0)
        dominant = summary.get("dominant_count", 0)
        category_row = ft.Column(
            [
                ft.Row(
                    [
                        category_checkbox,
                        SecondaryText("Also set category to"),
                        category_dd,
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                SecondaryText(
                    (
                        f"{dominant} of {total} already use it"
                        + (
                            f" · {summary['distinct_categories']} different "
                            "categories in this payee's history"
                            if summary.get("distinct_categories", 0) > 1
                            else ""
                        )
                    ),
                    size=Theme.Typography.CAPTION,
                ),
            ],
            spacing=2,
            tight=True,
            visible=offer_category,
        )

        def _on_selection(indices: set[int]) -> None:
            selected.clear()
            selected.update(indices)
            _sync_apply_label()

        def _sync_apply_label() -> None:
            apply_button.text = f"Apply to {len(selected)}" if items else "Apply"
            apply_button.disabled = not selected and not (
                offer_category and category_checkbox.value
            )
            if apply_button.page:
                apply_button.update()

        table = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=min(400, 44 + _DENSE_ROW_HEIGHT * len(items)),
            selectable=True,
            selected_indices=selected,
            on_selection_change=_on_selection,
            empty_message="No similar transactions.",
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        async def _apply_all() -> None:
            ids = [items[i]["id"] for i in sorted(selected) if i < len(items)]
            category_id = (
                int(category_dd.value)
                if offer_category and category_checkbox.value and category_dd.value
                else None
            )
            dialog.open = False
            self.page.update()
            if ids:
                # One call does both: the lookalikes get the payee, and
                # (when offered) the category rides along.
                await api.post(
                    "/api/v1/finance/transactions/assign-merchant",
                    json={
                        "transaction_ids": ids,
                        "merchant_id": merchant_id,
                        "category_id": category_id,
                    },
                )
            if category_id is not None:
                # Also settle the rows this payee ALREADY covers - the
                # whole point is that the payee ends up internally
                # consistent, not just the new arrivals.
                existing = await api.get(
                    "/api/v1/finance/transactions",
                    params={"page_size": 500, "merchant_id": merchant_id},
                )
                owned = (
                    [t["id"] for t in existing.get("items", [])]
                    if isinstance(existing, dict)
                    else []
                )
                if owned:
                    await api.post(
                        "/api/v1/finance/transactions/assign-merchant",
                        json={
                            "transaction_ids": owned,
                            "merchant_id": merchant_id,
                            "category_id": category_id,
                        },
                    )
            parts = []
            if ids:
                parts.append(f"payee set on {len(ids)} more")
            if category_id is not None:
                parts.append("category applied and remembered for this payee")
            if parts:
                SuccessSnackBar(f"Done - {', '.join(parts)}.").launch(self.page)
            await self._load()

        blurb = (
            f"{len(items)} other transaction"
            f"{'s' if len(items) != 1 else ''} with no payee look like this "
            "one. Untick anything that isn't a match."
            if items
            else "This payee's transactions aren't all filed the same way."
        )
        dialog = StyledAlertDialog(
            title="Finish setting up this payee",
            body=ft.Column(
                [
                    SecondaryText(blurb),
                    ft.Container(content=table, width=620, visible=bool(items)),
                    category_row,
                ],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                apply_button,
            ],
            width=660,
        )
        self.page.open(dialog)

    async def _load_holdings(self) -> None:
        """Investment detail: current positions plus recent activity (trades)."""
        if self._account is None:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        account_id = self._account["id"]
        data = await api.get(f"/api/v1/finance/accounts/{account_id}/holdings")
        items = data.get("items", []) if isinstance(data, dict) else []
        total = data.get("total", len(items)) if isinstance(data, dict) else len(items)
        portfolio = data.get("portfolio_value", 0) if isinstance(data, dict) else 0
        activity = await api.get(f"/api/v1/finance/accounts/{account_id}/trades")
        trades = activity.get("items", []) if isinstance(activity, dict) else []

        self._subtitle.value = (
            f"{total:,} holding{'s' if total != 1 else ''}"
            f"  ·  Portfolio value {_usd(portfolio)}"
        )
        if self._subtitle.page is not None:
            self._subtitle.update()

        if not items and not trades:
            self._body.content = EmptyStatePlaceholder(
                message="No holdings or activity in this account."
            )
            self._refresh()
            return

        sections: list[ft.Control] = []
        if items:
            holding_columns = [
                DataTableColumn("Ticker", width=90),
                DataTableColumn("Name"),
                DataTableColumn("Quantity", width=110, alignment="right"),
                DataTableColumn("Price", width=120, alignment="right"),
                DataTableColumn("Market Value", width=150, alignment="right"),
            ]
            holding_rows = [
                [
                    ft.Row(
                        [
                            ProviderIcon(
                                holding.get("name") or holding.get("ticker") or "?",
                                holding.get("icon_b64"),
                            ),
                            TableNameText(holding.get("ticker") or "?"),
                        ],
                        spacing=Theme.Spacing.SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    TableCellText(holding.get("name") or ""),
                    TableCellText(_qty(holding.get("quantity"))),
                    TableCellText(_usd(holding.get("price"))),
                    _amount_cell(holding.get("market_value", 0)),
                ]
                for holding in items
            ]
            sections.append(
                _investment_section(
                    "Positions",
                    DataTable(
                        columns=holding_columns,
                        rows=holding_rows,
                        empty_message="No holdings",
                    ),
                )
            )
        if trades:
            trade_columns = [
                DataTableColumn("Date", width=120),
                DataTableColumn("Activity", width=110),
                DataTableColumn("Security"),
                DataTableColumn("Quantity", width=100, alignment="right"),
                DataTableColumn("Amount", width=140, alignment="right"),
            ]
            trade_rows = [
                [
                    date_cell(trade.get("trade_date")),
                    TableNameText(_trade_type_label(trade.get("type"))),
                    TableCellText(trade.get("name") or ""),
                    TableCellText(_qty(trade.get("quantity"))),
                    _amount_cell(trade.get("amount", 0)),
                ]
                for trade in trades
            ]

            def _expand_trade(index: int, _trades: list = trades) -> ft.Control:
                return _trade_expanded_content(_trades[index])

            sections.append(
                _investment_section(
                    "Activity",
                    DataTable(
                        columns=trade_columns,
                        rows=trade_rows,
                        empty_message="No activity",
                        expandable_content=_expand_trade,
                        # Virtualized: an investment account can carry
                        # hundreds of activity rows.
                        scroll_height=320,
                    ),
                )
            )
        self._body.content = ft.Column(
            sections,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=Theme.Spacing.LG,
        )
        self._refresh()

    def _refresh(self) -> None:
        if self._body.page is not None:
            self._body.update()

    # -- Account management ---------------------------------------------------

    def _open_rename(self, account: dict) -> None:
        value = {"name": account.get("name", "")}
        field = FormTextField(
            label="Account name",
            value=account.get("name", ""),
            on_change=lambda e: value.__setitem__(
                "name", (getattr(e.control, "value", "") or "").strip()
            ),
            width=360,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _save() -> None:
            dialog.open = False
            self.page.update()
            new_name = value["name"]
            if new_name and new_name != account.get("name"):
                await self._do_rename(account["id"], new_name)

        # ConfirmDialog's look but carrying a text field, which
        # ConfirmDialog doesn't support.
        dialog = StyledAlertDialog(
            title="Rename account",
            body=field,
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    def _open_reconcile(self, account: dict) -> None:
        """FIN-37: reconcile the register to a bank statement.

        Two presses of one button: the first computes the register-vs-
        statement difference (a pure read) and shows it; the second - with
        the same inputs - applies it as one transfer-flagged adjustment
        that never counts as spending. Changing either input drops back
        to the compute step.
        """
        from datetime import date as date_cls

        date_field = FormDateField(
            label="As of date", value=date_cls.today().isoformat(), width=380
        )
        balance_field = FormTextField(
            label="Actual balance ($)",
            hint="What the account really held on that date",
            width=380,
        )
        summary = ft.Column([], spacing=Theme.Spacing.XS, tight=True)
        state: dict[str, Any] = {"previewed": None}

        def _set_confirm(label: str) -> None:
            # PulseButton renders its label from a content Text built at
            # construction - repaint that, not just the stored attr.
            confirm.text = label
            confirm.content.value = label
            if confirm.page is not None:
                confirm.update()

        def _cents() -> int | None:
            raw = (balance_field.value or "").replace("$", "").replace(",", "")
            raw = raw.strip()
            if not raw:
                return None
            try:
                return round(float(raw) * 100)
            except ValueError:
                return None

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _submit() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            cents = _cents()
            if cents is None or not date_field.value:
                ErrorSnackBar(
                    "Enter the date and the balance the account really had."
                ).launch(self.page)
                return
            api = get_session_state(self.page).api_client
            payload = {
                "statement_date": date_field.value,
                "statement_balance": cents,
            }
            if state["previewed"] != (date_field.value, cents):
                result = await api.post(
                    f"/api/v1/finance/accounts/{account['id']}/reconcile",
                    json={**payload, "preview": True},
                )
                if not isinstance(result, dict):
                    ErrorSnackBar(
                        api.last_error or "Could not compute the difference."
                    ).launch(self.page)
                    return
                state["previewed"] = (date_field.value, cents)
                delta = result.get("delta", 0)
                sign = "+" if delta > 0 else "-"
                when = format_date(result.get("statement_date"))
                lines: list[ft.Control] = [
                    SecondaryText(
                        f"The app shows (through {when}): "
                        f"{_usd(result.get('register_balance', 0))}"
                    ),
                    SecondaryText(f"You say it was: {_usd(cents)}"),
                ]
                if delta == 0:
                    lines.append(
                        SecondaryText(
                            "They already match - nothing to fix.",
                            color=Theme.Colors.SUCCESS,
                        )
                    )
                    _set_confirm("Mark reconciled")
                else:
                    lines.append(
                        SecondaryText(
                            f"The fix: a {sign}{_usd(abs(delta))} adjustment",
                            color=Theme.Colors.WARNING,
                        )
                    )
                    lines.append(
                        SecondaryText(
                            (
                                f"Posting records {_usd(cents)} as this "
                                f"account's value on {when} - it has no "
                                "transactions to adjust."
                            )
                            if result.get("route") == "valuation"
                            else (
                                f"Posting adds one 'Balance adjustment' "
                                f"transaction dated {when}, bringing the "
                                f"account to {_usd(cents)}. It never counts "
                                "as spending."
                            ),
                            size=Theme.Typography.BODY_SMALL,
                        )
                    )
                    _set_confirm("Post adjustment")
                summary.controls = lines
                if summary.page is not None:
                    summary.update()
                return

            result = await api.post(
                f"/api/v1/finance/accounts/{account['id']}/reconcile",
                json=payload,
            )
            if not isinstance(result, dict):
                ErrorSnackBar(
                    api.last_error or "Could not reconcile the account."
                ).launch(self.page)
                return
            dialog.open = False
            self.page.update()
            SuccessSnackBar(
                f"{account.get('name', 'Account')} reconciled through "
                f"{format_date(result.get('reconciled_through'))}."
            ).launch(self.page)
            await self._load()
            if self._reload_accounts is not None:
                await self._reload_accounts(account["id"])

        confirm = PulseButton(
            on_click_callable=_submit,
            text="Check",
            variant="teal",
            compact=True,
        )
        dialog = StyledAlertDialog(
            title="Reconcile account",
            body=ft.Column(
                [date_field, balance_field, summary],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                confirm,
            ],
            width=440,
        )
        self.page.open(dialog)

    def _open_remove(self, account: dict) -> None:
        ConfirmDialog(
            page=self.page,
            title="Remove account",
            message=(
                f'Remove "{account.get("name", "")}"? It will be hidden from '
                "your accounts. Its history is kept and not deleted."
            ),
            confirm_text="Remove",
            destructive=True,
            on_confirm=lambda: self._do_remove(account["id"]),
        ).show()

    async def _do_rename(self, account_id: int, name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.patch(
            f"/api/v1/finance/accounts/{account_id}", json={"name": name}
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not rename the account.").launch(self.page)
            return
        SuccessSnackBar(f"Renamed to {name}.").launch(self.page)
        if self._reload_accounts is not None:
            await self._reload_accounts(account_id)

    async def _do_remove(self, account_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/accounts/{account_id}")
        SuccessSnackBar("Account removed.").launch(self.page)
        if self._reload_accounts is not None:
            await self._reload_accounts(None)


class AccountsTab(ft.Container):
    """The register tab: account sidebar + transaction/holdings detail."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__()
        self.expand = True
        panel = TransactionsPanel(page, account_filter, register_filter_listener)
        # Composite, not a FinancePanel: it has no _load of its own.
        # A dialog-level revisit still has to reach the register it
        # hosts, or edits made on other tabs (a payee named in
        # Review) go stale here silently - the same drift class the
        # base exists to kill.
        self._panel = panel
        sidebar = AccountsSidebar(
            page,
            on_select=panel.select,
            on_import_transactions=panel.open_transactions_import_picker,
            on_import_investments=panel.open_investments_import_picker,
        )
        panel.set_reload_hook(sidebar.reload)
        self.content = ft.Row([sidebar, panel], spacing=0, expand=True)

    def refresh_on_revisit(self) -> None:
        if self._panel.page:
            self._panel.page.run_task(self._panel._load)


def _list_card(
    title: str,
    rows: list[ft.Control],
    *,
    on_click: Callable[[], None] | None = None,
) -> ft.Control:
    """Card chrome around a list of rows, matching the chart cards.

    The ranked-bar cards draw their own surface; a plain list needs the
    same one, or it reads as loose text beside boxed neighbours.

    ``on_click`` makes the whole card a button (ink ripple, no arg) - for
    a card that is a preview of something actionable elsewhere, like the
    Uncategorized card opening its own dialog.
    """
    card = ft.Container(
        content=ft.Column(
            [SecondaryText(title, size=Theme.Typography.BODY_SMALL), *rows],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=Theme.Spacing.MD,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.border.all(0.5, ft.Colors.OUTLINE),
        border_radius=Theme.Components.CARD_RADIUS,
    )
    if on_click is not None:
        card.on_click = lambda _e: on_click()
        card.ink = True
    return card


def _overview_row(label: str, sublabel: str, amount: int, color: str) -> ft.Control:
    """A labeled amount row for the Overview breakdowns (group totals + spending
    by category). One shape, two callers."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    label,
                    size=Theme.Typography.BODY,
                    color=Theme.Colors.TEXT_PRIMARY,
                    weight=ft.FontWeight.W_500,
                    expand=True,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Text(
                    sublabel,
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                ),
                NumericText(
                    _usd(amount),
                    size=Theme.Typography.BODY,
                    color=color,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(
            vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
        ),
        border=ft.border.only(bottom=ft.BorderSide(1, Theme.Colors.BORDER_SUBTLE)),
    )


class AccountFilterButton(Dropdown):
    """Multi-select account-scope filter: a ``Dropdown`` trigger reading
    "All accounts" / "N of M accounts", opening a checkable-dot panel
    grouped the same way the Accounts sidebar is (``_ACCOUNT_GROUPS``).

    Extracted from ``OverviewTab`` (its original, only home) so
    ``UncategorizedPanel`` can offer the exact same filter instead of
    inventing a second account picker. Owns its own ``AccountFilter``
    state unless one is passed in - pass the dialog-level shared
    instance (``FinanceDetailDialog._account_filter``) so a narrower
    view keeps following the user from Overview into Review too.
    ``set_accounts`` rebuilds the menu from a freshly fetched account
    list; the caller's ``on_change`` fires after every toggle so it can
    reload its own data - this control has no idea what that data is.
    """

    def __init__(
        self,
        *,
        on_change: Callable[[], None],
        account_filter: AccountFilter | None = None,
    ) -> None:
        self.filter = account_filter or AccountFilter()
        self._on_change = on_change
        super().__init__(
            trigger=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.FILTER_ALT_OUTLINED,
                        size=16,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    SecondaryText("All accounts", size=Theme.Typography.BODY_SMALL),
                ],
                spacing=4,
                tight=True,
            ),
        )

    def set_accounts(self, accounts: list[dict]) -> None:
        """Check marks show what is in view: with no filter every account
        is checked, because that is what "All accounts" means. Toggling
        the last account off (or every account on) collapses back to
        All - a zero-account dashboard is a dead end nobody asks for."""
        all_ids = [a.get("id") for a in accounts if a.get("id") is not None]
        active = self.filter.selected is not None

        def show_all(_e: ft.ControlEvent) -> None:
            self.filter.selected = None
            self._on_change()

        def remove_all(_e: ft.ControlEvent) -> None:
            self.filter.selected = set()
            self._on_change()

        def toggler(account_id: int):
            def _toggle(_e: ft.ControlEvent) -> None:
                self.filter.toggle(account_id, all_ids)
                self._on_change()

            return _toggle

        def dot(selected: bool) -> ft.Container:
            # The same dot language the chart legends use: teal fill when
            # the account is in view, a hollow outline when it is not.
            return ft.Container(
                width=10,
                height=10,
                border_radius=5,
                bgcolor=Theme.Colors.ACCENT if selected else None,
                border=None if selected else ft.border.all(1.5, ft.Colors.OUTLINE),
            )

        def entry(leading: ft.Control, label: str, on_click: Callable) -> ft.Container:
            # ``ink=True`` gives the Material press ripple that stock
            # PopupMenuItem got for free; here it's a plain row inside the
            # Dropdown's own panel, so it has to be asked for explicitly.
            # Deliberately doesn't close the dropdown - picking accounts is
            # a multi-select, so each click should just update that row's
            # dot and leave the panel open for the next one. It closes via
            # its own trigger or an outside click instead.
            return ft.Container(
                content=ft.Row(
                    [leading, ft.Text(label, size=13, color=ft.Colors.ON_SURFACE)],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                on_click=on_click,
                ink=True,
                border_radius=Theme.Components.BUTTON_RADIUS,
                padding=ft.padding.symmetric(
                    vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
                ),
            )

        def header(text: str) -> ft.Container:
            # Same caption treatment as the sidebar's group headers.
            return ft.Container(
                content=ft.Text(
                    text,
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                    weight=ft.FontWeight.W_600,
                ),
                padding=ft.padding.only(
                    left=Theme.Spacing.MD,
                    right=Theme.Spacing.MD,
                    top=Theme.Spacing.MD,
                    bottom=Theme.Spacing.XS,
                ),
            )

        rows: list[ft.Control] = [
            entry(dot(not active), "All accounts", show_all),
            entry(
                ft.Icon(
                    ft.Icons.CLEAR_ALL,
                    size=14,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                "Remove all",
                remove_all,
            ),
            ft.Divider(height=1, color=Theme.Colors.BORDER_SUBTLE),
        ]
        # Same buckets, same order as the Accounts sidebar - the picker
        # should read like a compact copy of the page it filters.
        grouped: dict[str, list[dict]] = {}
        for account in accounts:
            if account.get("id") is None:
                continue
            grouped.setdefault(_group_for(account.get("account_type", "")), []).append(
                account
            )
        for group_label, _types in _ACCOUNT_GROUPS:
            group = grouped.get(group_label)
            if not group:
                continue
            rows.append(header(group_label))
            for account in group:
                account_id = account["id"]
                rows.append(
                    entry(
                        dot(self.filter.allows(account_id)),
                        str(account.get("name", "")),
                        toggler(account_id),
                    )
                )

        selected_count = sum(1 for i in all_ids if self.filter.allows(i))
        label = (
            "All accounts"
            if not active
            else f"{selected_count} of {len(all_ids)} accounts"
        )
        self.set_panel(
            ft.Column(rows, spacing=0, scroll=ft.ScrollMode.AUTO, tight=True)
        )
        self.set_trigger(
            ft.Row(
                [
                    ft.Icon(
                        ft.Icons.FILTER_ALT if active else ft.Icons.FILTER_ALT_OUTLINED,
                        size=16,
                        color=Theme.Colors.ACCENT
                        if active
                        else ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    SecondaryText(label, size=Theme.Typography.BODY_SMALL),
                ],
                spacing=4,
                tight=True,
            )
        )


class OverviewTab(FinancePanel):
    """Net-worth summary: assets, liabilities, net worth, a per-group breakdown,
    and spending by category. No sidebar — this is the landing view."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._body = ft.Column(
            spacing=Theme.Spacing.LG, scroll=ft.ScrollMode.AUTO, expand=True
        )
        # Built once, on first open, then reused - see _open_uncategorized.
        # A fresh dialog + UncategorizedPanel on every click (the original
        # design) never actually left page.overlay once closed: Flet's
        # page.close()/`.open = False` only hides a dialog, it doesn't
        # remove it or its subtree - so every reopen was a permanent leak.
        # This mirrors _open_modal's own cache pattern (card_utils.py) for
        # exactly that reason.
        #
        # OverlayStyledDialog, not StyledAlertDialog: this dialog's body
        # (UncategorizedPanel) hosts its own account-filter Dropdown - a
        # page.overlay-based popup - and a real ft.AlertDialog (what
        # StyledAlertDialog wraps) renders through Flutter's own dialog
        # route, which always paints above page.overlay content regardless
        # of append order. That nested Dropdown opened BEHIND this dialog
        # instead of above it (confirmed live) until this swap - see
        # OverlayStyledDialog's own docstring (base_popup.py).
        self._uncategorized_dialog: OverlayStyledDialog | None = None
        self._uncategorized_panel: UncategorizedPanel | None = None
        # One window drives every card on the page, so the pie, the bars
        # and the net-worth line always describe the same span - three
        # charts on different periods invite false comparisons.
        self._days = 180
        # Parallel to the pie's own ``slices`` (index i here -> the
        # category name(s) slice i represents) - rebuilt every ``_load``.
        # A named slice is one parent category (spending_by_category's own
        # rollup); "Other" is every name that didn't make the cut, which
        # is why this is a list of lists, not a list of names.
        self._pie_slice_categories: list[list[str]] = []
        # Header matches the Projected tab: title + subtitle on the left,
        # the headline figures bare against the right edge. Cards below
        # would cost the chart a card's height and box it twice.
        self._stats = ft.Row(
            [],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                H3Text("Net worth"),
                                SecondaryText(
                                    "Everything you own, less everything you owe"
                                ),
                            ],
                            spacing=2,
                        ),
                        ft.Container(expand=True),
                        DateRangeChips(
                            options=[
                                ("1m", 30),
                                ("3m", 90),
                                ("6m", 180),
                                ("1y", 365),
                                ("All", 9999),
                            ],
                            selected_days=self._days,
                            on_change=self._on_range,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                            icon_size=18,
                            tooltip="Refresh overview",
                            on_click=lambda e: e.page.run_task(self._load),
                        ),
                        self._stats,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.LG,
                ),
                # Separates the headline banner from the charts below, so
                # the figures read as a summary OF the page rather than as
                # a caption on the first card.
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def _on_range(self, days: int) -> None:
        self._days = days
        self._reload()

    def _on_pie_slice_click(self, index: int) -> None:
        if index >= len(self._pie_slice_categories) or not self.page:
            return
        categories = self._pie_slice_categories[index]
        label = categories[0] if len(categories) == 1 else "Other"

        # A real async function, not page.run_task(lambda: ...) - Page.run_task
        # asserts its handler is an actual coroutine function, which a lambda
        # wrapping a call is not (see the run_now fix in controls/debounce.py).
        async def _open() -> None:
            await self._open_category_drilldown(categories, label)

        self.page.run_task(_open)

    async def _open_category_drilldown(self, categories: list[str], label: str) -> None:
        """The transactions behind one pie slice - same DataTable + inline
        row-expand flow the Accounts register uses (TransactionsPanel._load).
        Built fresh per click rather than cached: unlike
        ``_open_uncategorized`` (always the same content), a different
        slice needs different rows every time, so there's nothing to reuse
        between opens. Row-expand rather than a second, nested dialog -
        this table already lives inside a ``StyledAlertDialog`` of its own.
        """
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        window = 3650 if self._days >= 9000 else self._days
        params: dict[str, object] = {
            "days": window,
            "categories": categories,
            **self._account_filter.params(),
        }
        data = await api.get("/api/v1/finance/spending/transactions", params=params)
        items = data.get("items", []) if isinstance(data, dict) else []

        columns = [
            DataTableColumn("Date", width=120),
            DataTableColumn("Payee", hideable=False),
            DataTableColumn("Category", width=200),
            DataTableColumn("Amount", width=150, alignment="right"),
        ]
        rows = [
            [
                date_cell(item.get("date")),
                TableNameText(item.get("name") or ""),
                TableCellText(item.get("category") or "—"),
                _amount_cell(item.get("amount", 0)),
            ]
            for item in items
        ]

        def _expand_detail(idx: int, _items: list = items) -> ft.Control:
            return _transaction_expanded_content(_items[idx])

        table = DataTable(
            columns=columns,
            rows=rows,
            empty_message="No transactions in this window.",
            scroll_height=440,
            expandable_content=_expand_detail,
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        dialog = StyledAlertDialog(
            title=f"{label} · last {window}d",
            body=ft.Container(content=table, width=780),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Close",
                    variant="muted",
                    compact=True,
                )
            ],
            width=820,
        )
        self.page.open(dialog)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/finance/accounts", params={"page_size": 200})
        all_items = data.get("items", []) if isinstance(data, dict) else []
        # Everything below describes only the accounts in view. An EMPTY
        # selection ("Remove all") must render an empty page - its params
        # would serialize to nothing and read as "no filter" server-side,
        # so the aggregate fetches are skipped outright instead.
        filter_empty = self._account_filter.is_empty
        items = [a for a in all_items if self._account_filter.allows(a.get("id"))]
        filter_params = self._account_filter.params()

        assets = sum(
            _account_display_balance(a)
            for a in items
            if a.get("classification") != "liability"
        )
        liabilities = sum(
            _account_display_balance(a)
            for a in items
            if a.get("classification") == "liability"
        )
        net_worth = assets + liabilities

        # Net-worth trend (materialized daily by the scheduler; empty until it
        # has run against real accounts).
        window = 3650 if self._days >= 9000 else self._days
        nw = (
            []
            if filter_empty
            else await api.get(
                "/api/v1/finance/net-worth",
                params={"days": window, **filter_params},
            )
        )
        points = nw if isinstance(nw, list) else []
        chart: ft.Control | None = None
        if len(points) >= 2:
            values = [p.get("net_worth_amount", 0) / 100 for p in points]
            chart = LineChartCard(
                title="Net worth over time",
                subtitle="",
                x_labels=[str(p.get("as_of_date", "")) for p in points],
                series=[
                    LineSeries(
                        label="Net Worth",
                        color=Theme.Colors.SUCCESS,
                        points=[(i, v) for i, v in enumerate(values)],
                        tooltips=[_usd(p.get("net_worth_amount", 0)) for p in points],
                        fill=True,
                        stroke_width=3,
                    )
                ],
                min_y=chart_floor(values),
            )

        self._stats.controls = [
            headline_stat("Assets", _usd(assets), headline_stat_color(assets)),
            headline_stat(
                "Liabilities", _usd(liabilities), headline_stat_color(liabilities)
            ),
            headline_stat("Net Worth", _usd(net_worth), headline_stat_color(net_worth)),
        ]
        if self._stats.page is not None:
            self._stats.update()

        # Per-group breakdown (same buckets as the sidebar).
        grouped: dict[str, list] = {}
        for account in items:
            grouped.setdefault(_group_for(account.get("account_type", "")), []).append(
                account
            )
        breakdown_rows: list[ft.Control] = []
        for label, _types in _ACCOUNT_GROUPS:
            group = grouped.get(label)
            if not group:
                continue
            subtotal = sum(_account_display_balance(a) for a in group)
            plural = "s" if len(group) != 1 else ""
            breakdown_rows.append(
                _overview_row(
                    label,
                    f"{len(group)} account{plural}",
                    subtotal,
                    _balance_color(subtotal),
                )
            )

        # Income vs spend per month - grouped bars, one axis. Two series get
        # the house ramp's most-separated pair (validated for CVD), never
        # red for spending: outflow is the assumption here, not an alarm.
        # Months, not days: 36 is the endpoint's ceiling and also as many
        # bars as fit before they turn into hairlines.
        months = max(1, min(240, round(window / 30)))
        cash = (
            {}
            if filter_empty
            else await api.get(
                "/api/v1/finance/cashflow",
                params={"months": months, **filter_params},
            )
        )
        cash_months = cash.get("items", []) if isinstance(cash, dict) else []
        cash_card: ft.Control | None = None
        if any(m.get("income") or m.get("expense") for m in cash_months):
            cash_months = _fold_cashflow(cash_months)
            cash_card = BarChartCard(
                x_labels=[str(m.get("label", "")) for m in cash_months],
                series=[
                    BarSeries(
                        "Income",
                        ChartColors.TEAL,
                        [(m.get("income") or 0) / 100 for m in cash_months],
                    ),
                    BarSeries(
                        "Spending",
                        ChartColors.VIOLET,
                        [(m.get("expense") or 0) / 100 for m in cash_months],
                    ),
                ],
                value_format=lambda v: f"${v:,.0f}",
            )

        # Who took the most, and what is about to hit. Both are ranked
        # lists rather than plots: the labels are names, and the ordering
        # is the point.
        payees = await api.get(
            "/api/v1/finance/payees", params={"days": window, "limit": 7}
        )
        payee_items = payees.get("items", []) if isinstance(payees, dict) else []
        payee_card: ft.Control | None = None
        if payee_items:
            payee_card = RankedBarCard(
                title=f"Top payees · {window}d",
                rows=[
                    RankedBar(
                        label=item.get("payee") or "",
                        value=(item.get("amount") or 0) / 100,
                        display=_usd(item.get("amount") or 0),
                        meta=f"{item.get('transaction_count', 0)}x",
                    )
                    for item in payee_items
                ],
            )

        # Upcoming bills come from the same projection the Projected tab
        # walks, so the two can never disagree about what is due.
        upcoming = await api.get(
            "/api/v1/finance/recurring/projection", params={"days": 30}
        )
        points = upcoming.get("points", []) if isinstance(upcoming, dict) else []
        bills = [p for p in points if (p.get("amount") or 0) < 0][:7]
        bills_card: ft.Control | None = None
        if bills:
            bills_card = RankedBarCard(
                title="Upcoming bills · next 30 days",
                rows=[
                    RankedBar(
                        label=bill.get("name") or "",
                        value=abs(bill.get("amount") or 0) / 100,
                        display=_usd(abs(bill.get("amount") or 0)),
                        meta=str(bill.get("date", ""))[5:],
                    )
                    for bill in bills
                ],
                color=ChartColors.VIOLET,
            )

        # Recent transactions: the ledger itself, newest first. Not ranked
        # and not plotted - it answers "what just happened", where the
        # ORDER is the information, so bars would be actively misleading.
        recent = await api.get("/api/v1/finance/transactions", params={"page_size": 7})
        recent_items = recent.get("items", []) if isinstance(recent, dict) else []
        recent_card: ft.Control | None = None
        if recent_items:
            recent_card = _list_card(
                "Recent transactions",
                [
                    _overview_row(
                        item.get("name") or "",
                        f"{item.get('date', '')} · {item.get('category') or 'uncategorized'}",
                        item.get("amount") or 0,
                        ledger_amount_color(item.get("amount") or 0),
                    )
                    for item in recent_items
                ],
            )

        # Uncategorized: work waiting, not a metric. The title carries the
        # FULL backlog count while the rows show only the newest few, so
        # the card says how much there is without pretending to list it.
        uncat = await api.get("/api/v1/finance/uncategorized", params={"limit": 7})
        uncat_items = uncat.get("items", []) if isinstance(uncat, dict) else []
        uncat_total = uncat.get("total", 0) if isinstance(uncat, dict) else 0
        uncat_card: ft.Control | None = None
        if uncat_items:
            uncat_card = _list_card(
                f"Uncategorized · {uncat_total:,} to review",
                [
                    _overview_row(
                        item.get("name") or "",
                        str(item.get("date", "")),
                        item.get("amount") or 0,
                        ledger_amount_color(item.get("amount") or 0),
                    )
                    for item in uncat_items
                ],
                on_click=self._open_uncategorized,
            )

        # Spending by category (last 30 days) — outflows, largest first.
        spending = (
            []
            if filter_empty
            else await api.get(
                "/api/v1/finance/spending",
                params={"days": window, **filter_params},
            )
        )
        spend_list = spending if isinstance(spending, list) else []
        # ``category`` here is already the PARENT category name -
        # spending_by_category rolls up "Parent:Child" leaves before it
        # ever reaches this endpoint (finance_service.py), specifically
        # so this pie doesn't fragment a real ledger's spending across
        # every sub-category and dump most of it in "Other" (was 30.7%
        # leaf-grouped on real data, 16.3% parent-rolled-up, 5.3% at
        # _PIE_CATEGORIES=15 - the fix lives server-side, not here; the
        # slice COUNT is tuned above). The legend scrolls if it runs past
        # the chart's own height (modal_sections.py) rather than clipping
        # entries silently; the tail keeps a fixed neutral color so it
        # reads as tail, not category.
        pie_card: ft.Control | None = None
        top_spend = spend_list[:_PIE_CATEGORIES]
        self._pie_slice_categories = []
        if top_spend:
            tail_items = spend_list[_PIE_CATEGORIES:]
            tail = sum(item.get("amount", 0) for item in tail_items)
            slices = [
                {
                    "value": item.get("amount", 0) / 100,
                    "label": item.get("category", ""),
                }
                for item in top_spend
            ]
            self._pie_slice_categories = [
                [item.get("category", "")] for item in top_spend
            ]
            if tail:
                slices.append(
                    {
                        "value": tail / 100,
                        "label": "Other",
                        "color": PIE_CHART_TAIL_COLOR,
                    }
                )
                self._pie_slice_categories.append(
                    [item.get("category", "") for item in tail_items]
                )
            pie_card = PieChartCard(
                "Spending by category",
                slices,
                value_formatter=lambda value: f"${value:,.2f}",
                on_slice_click=self._on_pie_slice_click,
                # This card sits in a Row stretched to _OVERVIEW_CARD_HEIGHT
                # (320px) - PieChartCard's own default 130px chart left most
                # of that height empty (see chart_size's own docstring).
                # 230 -> a 310px card, close to the 320 stretch target.
                chart_size=230,
            )

        spend_rows = [
            _overview_row(
                s.get("category", ""),
                "",
                s.get("amount", 0),
                Theme.Colors.ERROR,
            )
            for s in spend_list[:_PIE_CATEGORIES]
        ]

        self._body.controls.clear()
        # One card row, three questions: where is it going (pie), am I
        # keeping any of it (bars), and where has it got me (net worth).
        # Each card expands, so the Row divides the width between however
        # many of them have data.
        # Each card is wrapped in an expanding Container so the Row hands
        # it a FINITE width. Charts inside are ``expand=True``; in a Row
        # with no bound that resolves to infinity and fl_chart fails to
        # lay out, which is why an unwrapped card row renders blank.
        card_row = [c for c in (chart, pie_card, cash_card) if c is not None]
        if card_row:
            self._body.controls.append(
                ft.Row(
                    [ft.Container(content=card, expand=True) for card in card_row],
                    spacing=Theme.Spacing.MD,
                    # STRETCH, not START: cards whose content differs in
                    # height (a donut is shorter than a plot + legend)
                    # otherwise end at three different baselines.
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    height=_OVERVIEW_CARD_HEIGHT,
                )
            )
        # Second row: the two ranked lists. Kept off the first row so the
        # plots there keep enough width to be readable.
        for row_cards in (
            (payee_card, bills_card, recent_card),
            (uncat_card,),
        ):
            cards = [c for c in row_cards if c is not None]
            if not cards:
                continue
            self._body.controls.append(
                ft.Row(
                    [ft.Container(content=card, expand=True) for card in cards],
                    spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    height=_OVERVIEW_CARD_HEIGHT,
                )
            )
        if breakdown_rows:
            self._body.controls.append(
                ft.Text(
                    "By group",
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                    weight=ft.FontWeight.W_600,
                )
            )
            self._body.controls.append(ft.Column(breakdown_rows, spacing=0))
        elif not items:
            self._body.controls.append(
                EmptyStatePlaceholder(message="No accounts yet.")
            )
        if spend_rows:
            self._body.controls.append(
                ft.Text(
                    "Spending · last 30 days",
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                    weight=ft.FontWeight.W_600,
                )
            )
            self._body.controls.append(ft.Column(spend_rows, spacing=0))
        if self._body.page is not None:
            self._body.update()

    def _open_uncategorized(self) -> None:
        """Build once, on first open, then reuse - ``page.close()``/
        ``dialog.open = False`` only hides a dialog, Flet never actually
        removes it (or its subtree) from ``page.overlay``, so a fresh
        dialog + ``UncategorizedPanel`` on every click was a permanent
        leak on every reopen. Same cache-and-refresh shape ``_open_modal``
        already uses for the whole Finance modal itself.
        """
        if self._uncategorized_dialog is None:
            # Same shared AccountFilter FinanceDetailDialog's own button
            # drives, so a narrower view set there keeps applying inside
            # this popup too - this panel builds its OWN button though
            # (register_filter_listener not given): the shared one lives
            # above the tab strip, which this popup covers when open, so
            # there'd be no way to reach it otherwise.
            #
            # 1200, not UncategorizedPanel's own 860 default: search,
            # account filter, seven date chips, and two buttons all share
            # one row, and narrower widths packed them edge to edge, and
            # left the table's own Payee column (the identity column, the
            # one actually worth reading) squeezed down to a handful of
            # characters before it ellipsed.
            panel = UncategorizedPanel(
                self.page, width=1200, account_filter=self._account_filter
            )
            self._uncategorized_panel = panel

            async def _done() -> None:
                dialog.hide()
                self.page.update()
                await self._load()

            dialog = OverlayStyledDialog(
                self.page,
                title="Uncategorized transactions",
                body=panel,
                width=1200,
                actions=[
                    PulseButton(on_click_callable=_done, text="Done", compact=True)
                ],
            )
            self._uncategorized_dialog = dialog
            # OverlayStyledDialog isn't auto-attached to the page the way
            # page.open() handles a real AlertDialog - caller owns this
            # one-time append (see its own docstring).
            self.page.overlay.append(dialog)
        else:
            # Reopening a cached panel - did_mount already fired once and
            # won't again, so this is what keeps the data from going stale.
            self._uncategorized_panel.refresh()
        self._uncategorized_dialog.show()
        self.page.update()


# Connection status -> (display label, severity). Severity drives the shared
# StatusTag dot styling, so colors stay single-sourced in the theme instead
# of being re-picked per feature.
_STATUS_STYLE: dict[str, tuple[str, ComponentStatusType]] = {
    "healthy": ("Connected", ComponentStatusType.HEALTHY),
    "loading": ("Syncing", ComponentStatusType.WARNING),
    "login_required": ("Login required", ComponentStatusType.WARNING),
    "pending_expiration": ("Expiring soon", ComponentStatusType.WARNING),
    "pending_disconnect": ("Disconnecting", ComponentStatusType.WARNING),
    "consent_expired": ("Consent expired", ComponentStatusType.UNHEALTHY),
    "revoked": ("Disconnected", ComponentStatusType.UNHEALTHY),
    "error": ("Error", ComponentStatusType.UNHEALTHY),
    "manual": ("Manual", ComponentStatusType.INFO),
}


def _status_style(status: str) -> tuple[str, ComponentStatusType]:
    return _STATUS_STYLE.get(
        status,
        (status.replace("_", " ").title(), ComponentStatusType.INFO),
    )


def _connection_title(conn: dict) -> str:
    if conn.get("label"):
        return conn["label"]
    provider = (conn.get("provider") or "connection").title()
    environment = (conn.get("environment") or "").title()
    return f"{provider} · {environment}" if environment else provider


# Connection cards lay out in a wrapping grid so account rows stay a comfortable

# Plaid sandbox test credentials (public, from Plaid's sandbox docs). Surfaced
# inside the connect-a-bank flow when PLAID_ENV is "sandbox" - handed over at
# the moment they get typed into Plaid's hosted connect screen.
_PLAID_SANDBOX_CREDENTIALS: tuple[tuple[str, str], ...] = (
    ("Username", "user_good"),
    ("Password", "pass_good"),
    ("Phone", "+1 415 555 0011"),
    ("OTP code", "123456"),
    ("Security answer", "1234"),
)


class ConnectionCard(ft.Container):
    """Collapsible card for the Connections grid.

    One anatomy for everything in the grid — provider connections, the
    manual/imported bucket, and the Plaid sandbox helper: a header row
    (expand arrow + bold title + caption subtitle) that toggles the body,
    an optional ``Tag`` in the status slot, an optional trailing action
    control, and a ``DataTable`` body.
    """

    def __init__(
        self,
        *,
        title: str,
        subtitle: str | None = None,
        tag: ft.Control | None = None,
        action: ft.Control | None = None,
        columns: list[DataTableColumn],
        rows: list[list[ft.Control]],
        empty_message: str,
        on_row_click: Callable[[int], None] | None = None,
        expanded: bool = False,
    ) -> None:
        super().__init__()
        self._arrow = ExpandArrow(expanded=expanded)
        self._table = ft.Container(
            content=DataTable(
                columns=columns,
                rows=rows,
                empty_message=empty_message,
                on_row_click=on_row_click,
            ),
            visible=expanded,
        )
        title_col = ft.Column(
            [
                PrimaryText(
                    title,
                    size=Theme.Typography.BODY,
                    weight=ft.FontWeight.W_600,
                ),
                SecondaryText(subtitle or "", size=Theme.Typography.CAPTION),
            ],
            spacing=2,
            expand=True,
        )
        header_bits: list[ft.Control] = [
            ft.Container(
                content=ft.Row(
                    [self._arrow, title_col],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.XS,
                ),
                on_click=self._toggle,
                ink=True,
                expand=True,
                border_radius=Theme.Components.BUTTON_RADIUS,
            )
        ]
        if tag is not None:
            header_bits.append(tag)
        if action is not None:
            header_bits.append(action)
        elif tag is not None:
            # Reserve the action (kebab) slot so tags align in a column
            # across cards that do and don't carry an action.
            header_bits.append(ft.Container(width=40))
        self.content = ft.Column(
            [
                ft.Row(header_bits, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self._table,
            ],
            spacing=Theme.Spacing.SM,
        )
        # Two fluid columns on wide viewports, one on narrow: the grid fills
        # the tab's width, so header controls (Connect / refresh) sit over
        # card content instead of dead space past a fixed-width grid.
        self.col = {"sm": 12, "lg": 6}
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.bgcolor = Theme.Colors.SURFACE_1
        self.border = ft.border.all(1, Theme.Colors.BORDER_SUBTLE)
        self.border_radius = Theme.Components.CARD_RADIUS

    def _toggle(self, _e: ft.ControlEvent) -> None:
        self._arrow.toggle()
        self._table.visible = self._arrow.expanded
        self._arrow.update()
        self._table.update()


def _plaid_sandbox_card(page: ft.Page) -> ConnectionCard:
    """The Plaid sandbox helper, composed from the same ``ConnectionCard``
    as every provider card. Clicking a credential row copies its value."""

    def _copy_row(index: int) -> None:
        label, value = _PLAID_SANDBOX_CREDENTIALS[index]
        page.set_clipboard(value)
        SuccessSnackBar(f"{label} copied").launch(page)

    return ConnectionCard(
        title="Plaid",
        subtitle="Test credentials for the connect screen  ·  click a row to copy",
        tag=StatusTag(status=ComponentStatusType.WARNING, text="Sandbox"),
        columns=[
            DataTableColumn("Credential"),
            DataTableColumn("Value", width=180, alignment="right"),
        ],
        rows=[
            [TableNameText(label), TableCellText(value)]
            for label, value in _PLAID_SANDBOX_CREDENTIALS
        ],
        empty_message="No credentials",
        on_row_click=_copy_row,
    )


class ConnectionsTab(FinancePanel):
    """See every account and how it's connected, and disconnect at any time.

    One card per provider connection (its accounts nested inside, with a
    Disconnect button); a final "Manual & imported" card for accounts that have
    no connection."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(page)
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._body = ft.Column(
            spacing=Theme.Spacing.MD, scroll=ft.ScrollMode.AUTO, expand=True
        )
        connect = _build_connect_menu(
            lambda e: e.page.run_task(self._connect_bank),
            lambda e: e.page.run_task(self._connect_brokerage),
        )
        self.content = ft.Column(
            [
                _refresh_row(
                    lambda e: e.page.run_task(self._load),
                    "Refresh connections",
                    leading=[connect] if connect is not None else None,
                ),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    async def _connect_bank(self) -> None:
        await _connect_bank_flow(self.page, self._load)

    async def _connect_brokerage(self) -> None:
        await _connect_brokerage_flow(self.page, self._load)

    def _card(
        self,
        title: str,
        accounts: list[dict],
        *,
        status: str | None = None,
        subtitle: str | None = None,
        on_disconnect=None,
    ) -> ft.Control:
        # Aligned columns (Account / Type / Balance) — same DataTable the
        # Accounts tab uses for transactions, so the type reads as a quiet
        # column instead of a loud per-row pill.
        tag = None
        if status is not None:
            label, severity = _status_style(status)
            # Same dot indicator the rest of the Overseer uses for status.
            tag = StatusTag(status=severity, text=label)
        action = None
        if on_disconnect is not None:
            # Kebab menu keeps destructive actions out of the resting view.
            action = ActionMenu(
                [
                    ActionMenuItem(
                        "Disconnect",
                        ft.Icons.LINK_OFF,
                        lambda e: e.page.run_task(on_disconnect),
                        destructive=True,
                    )
                ]
            )
        return ConnectionCard(
            title=title,
            subtitle=subtitle,
            tag=tag,
            action=action,
            columns=[
                DataTableColumn("Account"),
                DataTableColumn("Type", width=120),
                DataTableColumn("Balance", width=130, alignment="right"),
            ],
            rows=[
                [
                    TableNameText(account.get("name", "")),
                    TableCellText(
                        (account.get("account_type") or "").replace("_", " ").title()
                    ),
                    _amount_cell(_account_display_balance(account)),
                ]
                for account in accounts
            ],
            empty_message="No accounts.",
        )

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        conn_data = await api.get("/api/v1/finance/connections")
        acct_data = await api.get("/api/v1/finance/accounts", params={"page_size": 200})
        connections = conn_data.get("items", []) if isinstance(conn_data, dict) else []
        accounts = acct_data.get("items", []) if isinstance(acct_data, dict) else []

        by_connection: dict[int, list[dict]] = {}
        unconnected: list[dict] = []
        for account in accounts:
            cid = account.get("connection_id")
            if cid is None:
                unconnected.append(account)
            else:
                by_connection.setdefault(cid, []).append(account)

        cards: list[ft.Control] = []
        for conn in connections:
            conn_accounts = by_connection.get(conn["id"], [])
            synced = conn.get("last_successful_sync_at")
            synced_text = (
                f"Last synced {str(synced).split('T')[0]}" if synced else "Never synced"
            )
            subtitle = (
                f"{len(conn_accounts)} account"
                f"{'s' if len(conn_accounts) != 1 else ''}  ·  {synced_text}"
            )
            cards.append(
                self._card(
                    _connection_title(conn),
                    conn_accounts,
                    status=conn.get("status"),
                    subtitle=subtitle,
                    on_disconnect=self._disconnect_handler(conn, len(conn_accounts)),
                )
            )

        if unconnected:
            cards.append(
                self._card(
                    "Manual & imported",
                    unconnected,
                    subtitle="Not connected — added manually or from a file import.",
                )
            )

        # Sandbox helper rides the same grid as the provider cards, styled
        # identically, so the Plaid test credentials are always reachable
        # while a hosted connect screen is asking for them.
        if settings.FINANCE_PLAID and settings.PLAID_ENV == "sandbox":
            cards.append(_plaid_sandbox_card(self.page))

        self._body.controls.clear()
        if cards:
            self._body.controls.append(
                ft.ResponsiveRow(
                    cards,
                    spacing=Theme.Spacing.MD,
                    run_spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )
        else:
            self._body.controls.append(
                EmptyStatePlaceholder(message="No accounts or connections yet.")
            )
        if self._body.page is not None:
            self._body.update()

    def _disconnect_handler(self, conn: dict, account_count: int):
        """An async no-arg click handler (PulseButton's contract) that opens the
        disconnect confirmation for this connection."""

        async def _handler() -> None:
            self._open_disconnect(conn, account_count)

        return _handler

    def _open_disconnect(self, conn: dict, account_count: int) -> None:
        noun = f"{account_count} account{'s' if account_count != 1 else ''}"
        ConfirmDialog(
            page=self.page,
            title="Disconnect",
            message=(
                f"Disconnect {_connection_title(conn)}? This removes {noun} and "
                "stops syncing. Transaction history is kept and not deleted."
            ),
            confirm_text="Disconnect",
            destructive=True,
            on_confirm=lambda: self._do_disconnect(conn["id"]),
        ).show()

    async def _do_disconnect(self, connection_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/connections/{connection_id}")
        SuccessSnackBar("Disconnected.").launch(self.page)
        await self._load()


class ReviewTab(FinancePanel):
    """Three sub-tabs of things waiting on a decision, not one screen.

    - Uncategorized: the same work queue as the Overview card's dialog
      (``UncategorizedPanel``, own instance, own data load - not a link
      to that dialog, just the same reusable class). Shares the outer
      dialog's one ``AccountFilter`` AND its one filter button (pinned
      above the tab strip, not rebuilt per tab) - a narrower view set
      there keeps applying here, live, via ``register_filter_listener``.
    - Transfers: suggested transfers - pairs the detector matched but
      wasn't sure enough about to auto-hide (so nothing is silently
      removed from spend). Confirm excludes both legs from reports;
      Reject keeps them as normal spend/income and the pair is never
      suggested again.
    - Attention: ``AttentionTab`` (moved here from its own top-level tab -
      analyst narration over the rule findings it was written from).
      ``analyst_enabled`` has to be threaded through from
      ``FinanceDetailDialog`` so ``with_notes`` matches what the metadata
      actually reports instead of silently defaulting to a different
      value.

    Nested ``PulseTabs`` (the same tab styling the outer Finance modal
    uses for Overview/Accounts/Review/...) rather than stacking sections
    in one scroll - unrelated review queues sharing a screen made it
    unclear which list you were even looking at.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        analyst_enabled: bool = False,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener, expand=True)
        # No padding here - it belongs on each sub-tab's own content, same
        # as SettingsTab (its wrapper carries none; ConnectionsTab and
        # CategoriesTab each pad themselves). Padding on this outer
        # Container would sit OUTSIDE the nested PulseTabs, widening the
        # gap between it and the Finance modal's own tab bar above it.
        self._body = ft.Column(
            spacing=Theme.Spacing.MD, scroll=ft.ScrollMode.AUTO, expand=True
        )
        transfers_view = ft.Container(
            content=ft.Column(
                [
                    _refresh_row(
                        lambda e: e.page.run_task(self._load), "Refresh suggestions"
                    ),
                    self._body,
                ],
                spacing=0,
                expand=True,
            ),
            padding=ft.padding.all(Theme.Spacing.LG),
            expand=True,
        )
        self._uncategorized = UncategorizedPanel(
            page,
            width=None,
            account_filter=account_filter,
            register_filter_listener=register_filter_listener,
        )
        self._uncategorized.padding = ft.padding.all(Theme.Spacing.LG)
        # Same shared AccountFilter (and the same live re-filtering) the
        # Uncategorized queue beside it uses - a narrower account view
        # follows you across every sub-tab here.
        self._no_payee = NoPayeePanel(
            page,
            account_filter=account_filter,
            register_filter_listener=register_filter_listener,
        )
        self._no_payee.padding = ft.padding.all(Theme.Spacing.LG)

        # Deferred: finance_attention_tab.py imports _refresh_row FROM this
        # module, so a top-level import here would be a cycle.
        from .finance_attention_tab import AttentionTab

        self._attention = AttentionTab(page, with_notes=analyst_enabled)

        self.content = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Uncategorized", content=self._uncategorized),
                ft.Tab(text="No payee", content=self._no_payee),
                ft.Tab(text="Transfers", content=transfers_view),
                ft.Tab(text="Attention", content=self._attention),
            ],
            expand=True,
        )

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(
            "/api/v1/finance/transfers", params={"status": "suggested"}
        )
        suggestions = data.get("items", []) if isinstance(data, dict) else []
        acct_data = await api.get("/api/v1/finance/accounts", params={"page_size": 200})
        accounts = acct_data.get("items", []) if isinstance(acct_data, dict) else []
        name_by_id = {a["id"]: a.get("name", "Account") for a in accounts}

        self._body.controls.clear()
        if not suggestions:
            self._body.controls.append(
                EmptyStatePlaceholder(
                    message="No transfers to review. Matches we're confident "
                    "about are paired automatically."
                )
            )
        else:
            count = len(suggestions)
            self._body.controls.append(
                SecondaryText(
                    f"{count} possible transfer{'s' if count != 1 else ''} to review"
                )
            )
            self._body.controls.extend(
                self._row(item, name_by_id) for item in suggestions
            )
        if self._body.page is not None:
            self._body.update()

    def _row(self, item: dict, name_by_id: dict) -> ft.Control:
        frm = name_by_id.get(item.get("from_account_id"), "Account")
        to = name_by_id.get(item.get("to_account_id"), "Account")
        # Lead with the two legs' descriptions — that's what makes a real
        # transfer ("AMEX EPAYMENT -> PAYMENT RECEIVED") obvious from a
        # coincidence ("Starbucks -> INTRST PYMNT"). Each leg is clickable and
        # opens its full transaction detail (same dialog as the register).
        from_txn = item.get("from_transaction") or {}
        to_txn = item.get("to_transaction") or {}
        transfer_date = str(item.get("transfer_date") or "").split("T")[0]
        confidence = item.get("confidence")
        meta_bits = [f"{frm} -> {to}", transfer_date]
        if confidence is not None:
            meta_bits.append(f"{confidence}% match")
        if item.get("is_credit_card_payment"):
            meta_bits.append("card payment")
        header = ft.Row(
            [
                self._leg(from_txn, frm),
                SecondaryText("→"),
                self._leg(to_txn, to),
                ft.Container(expand=True),
                _amount_cell(item.get("amount") or 0),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=Theme.Spacing.SM,
        )
        actions = ft.Row(
            [
                PulseButton(
                    on_click_callable=self._action(item["id"], "confirm"),
                    text="Confirm",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=self._action(item["id"], "reject"),
                    text="Reject",
                    variant="stop",
                    compact=True,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        return ft.Container(
            content=ft.Column(
                [
                    header,
                    ft.Row(
                        [
                            SecondaryText("  ·  ".join(meta_bits)),
                            ft.Container(expand=True),
                            actions,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=Theme.Spacing.XS,
            ),
            padding=ft.padding.all(Theme.Spacing.MD),
            bgcolor=Theme.Colors.SURFACE_1,
            border=ft.border.all(1, Theme.Colors.BORDER_SUBTLE),
            border_radius=Theme.Components.CARD_RADIUS,
        )

    def _leg(self, txn: dict, account_name: str) -> ft.Control:
        """A clickable leg description that opens its full transaction
        detail (same field mapper as the register) - the one remaining
        RecordDetailDialog use in this module. Not a DataTable row (it's a
        transfer-match card, two legs side by side), so there's no row to
        expand inline the way every other transaction surface now does."""
        label = (txn.get("name") if txn else None) or account_name
        text = PrimaryText(label, weight=Theme.Typography.WEIGHT_SEMIBOLD)
        if not txn:
            return text
        return ft.Container(
            content=text,
            on_click=lambda _e, t=txn: RecordDetailDialog(
                self.page,
                "Transaction detail",
                transaction_detail_sections(t),
                hero=transaction_detail_hero(t),
                collapsed_sections=_TRANSACTION_COLLAPSED_SECTIONS,
            ).show(),
            ink=True,
            border_radius=Theme.Components.BUTTON_RADIUS,
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.XS),
            tooltip=transaction_tooltip(txn),
        )

    def _action(self, transfer_id: int, action: str):
        """No-arg async click handler (PulseButton's contract)."""

        async def _handler() -> None:
            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            await api.post(f"/api/v1/finance/transfers/{transfer_id}/{action}")
            message = (
                "Marked as a transfer." if action == "confirm" else "Kept as spending."
            )
            SuccessSnackBar(message).launch(self.page)
            await self._load()

        return _handler


class CompactIconButton(ft.IconButton):
    """A small accept/reject/clear affordance sized to its icon, not
    Material's default ~48px tap target - three of these plus a category
    name were what made every Uncategorized row feel loose regardless of
    the row's own height."""

    def __init__(
        self,
        icon: str,
        color: str,
        tooltip: str,
        on_click: Callable[[ft.ControlEvent], None],
    ) -> None:
        super().__init__(
            icon=icon,
            icon_size=14,
            icon_color=color,
            tooltip=tooltip,
            padding=0,
            size_constraints=ft.BoxConstraints(min_width=24, min_height=24),
            on_click=on_click,
        )


# Shared with _empty_cell below: build_cell's outer cell Container sets
# alignment=, and a Flutter Container with BOTH a size and an alignment
# shrink-wraps its child then positions it (Align), rather than
# stretching the child to fill the box - the child's OWN width has to be
# set explicitly to actually claim the full column, an ordinary
# content=content=content chain (no Row/Column ancestor to give an
# expand=True any flex meaning) won't do it on its own. Confirmed via
# the working _pending_cell/_suggested_cell pattern just below, which
# gets this right by putting expand=True on a Row child instead.
_CATEGORY_COLUMN_WIDTH = 240

_UNCATEGORIZED_COLUMNS = [
    DataTableColumn("Date", width=110),
    # Wide enough for a real account name ("Total Checking (Chase)")
    # without truncating.
    DataTableColumn("Account", width=220, style="secondary"),
    DataTableColumn("Payee", hideable=False),
    DataTableColumn("Amount", width=130, alignment="right"),
    # The accept/reject buttons are pinned by their own cells' expand=True
    # text wrapper now (see _pending_cell/_suggested_cell) - they no
    # longer get pushed off the edge by a long category name, so this
    # width is just "how much category text shows before it ellipses",
    # not load-bearing for the buttons' visibility the way it used to be.
    # 240, not the original 340 - that was starving Payee (the flex
    # column, and the one actually worth reading) down to a handful of
    # characters before it ellipsed (confirmed live: "Adj R…" for a
    # dialog whose Category column alone was claiming a third of it).
    #
    # sortable (the default) works here despite the cell being a Container
    # wrapping a Row of buttons, not plain text - _category_cell stamps
    # ``.data`` with the row's current category name (see
    # UncategorizedPanel._category_sort_text), and DataTable's generic
    # cell-text extraction falls back to that when a cell has no ``.value``
    # of its own. Same up/down-arrow header, same click-to-sort behavior
    # as every other column - no bespoke filter UI needed.
    DataTableColumn("Category", width=_CATEGORY_COLUMN_WIDTH, hideable=False),
]
# Fixed row height for DataTable's item_extent (paired with
# row_padding=6), sized to the common case: single-line cell text/a
# category pill + a 24px CompactIconButton + 6px padding on each side.
# Shared by every dense finance table in this file (Uncategorized, the
# Accounts register) so they read as one consistent density instead of
# each picking its own - the Accounts register originally shipped
# without either param (DataTable's own defaults: row_padding=10, no
# item_extent), which is what made it look visibly roomier next to
# Uncategorized (reported live from a side-by-side screenshot).
#
# Dropping item_extent entirely (tried once, for Uncategorized) let rows
# size to content, but also made ListView measure every row instead of
# using item_extent's O(1) scroll math - slower on a 900+ row backlog,
# and unclipping the list to let an open dropdown's popup escape (tried
# in the same pass) let ordinary row content bleed past the list's own
# bounds instead, into the header above it. Both reverted; the activated
# dropdown clipping (it needs ~240px, this row only offers 40) is still
# an open problem, not one this value can solve.
_DENSE_ROW_HEIGHT = 40
# Must cover the real backlog, not just a preview page: suggest_categories
# (the Auto-categorize sweep) is already unbounded, and a suggestion for a
# row past this limit would compute but never render - the row simply
# isn't in ``self._items`` to draw a cell for. High enough that a normal
# backlog (hundreds, occasionally low thousands after a big import) is
# never silently truncated; DataTable's ListView virtualization means the
# row COUNT loaded doesn't cost render time, only what's on screen does.
_UNCATEGORIZED_LOAD_LIMIT = 5000

# The no-payee queue is a different scale from the uncategorized backlog:
# EVERY transaction starts without a payee, so a real import opens at tens
# of thousands (17,644 here) rather than hundreds. A bounded page keeps the
# tab from building that many row trees; the header states the true total
# from the server so the number is never quietly understated, and search is
# the way through the list rather than scrolling all of it.
_NO_PAYEE_PAGE_SIZE = 500

# The cadences a bill can BE SET TO. Doubles as the "Repeats" dropdown's
# option list (finance_recurring_tab.py), which is why the two labels
# below are deliberately not in it.
# Menu text for every cadence, derived from the one table so the dropdown
# can never offer something create/update would reject.
_FREQUENCY_LABELS = {key: cadence.label for key, cadence in CADENCES.items()}
# What the Add/edit BILL dialogs offer: the cadences plus "One time" -
# a dated debt ("pay Bob back on the 15th") is a bill, not a rhythm, so
# it is statable here but never appears in cadence-only surfaces
# (detection, the declare-from-transactions dropdown).
BILL_FREQUENCY_OPTIONS = {
    **_FREQUENCY_LABELS,
    ONE_TIME_FREQUENCY: ONE_TIME_LABEL,
}
# Frequencies a stream can carry that detection never produces and
# nobody would pick from a menu: "irregular" is a real measured gap that
# matches no canonical cadence, "unknown" is a bill with only one
# transaction so far and therefore no gap to measure at all.
_DECLARED_FREQUENCY_LABELS = {
    "irregular": "Irregular",
    "unknown": "Not enough history yet",
    ONE_TIME_FREQUENCY: ONE_TIME_LABEL,
}


def _frequency_label(value: str) -> str:
    """Display text for a cadence, falling back to the raw value."""
    return (
        _FREQUENCY_LABELS.get(value) or _DECLARED_FREQUENCY_LABELS.get(value) or value
    )


# Vertical space the confirm dialog needs for everything that is NOT the
# table. Getting this WRONG IS NOT COSMETIC: StyledAlertDialog's panel
# clips (clip_behavior=HARD_EDGE) instead of shrinking, and the action row
# is the last child - so an over-tall table silently cuts off Cancel and
# the confirm button, leaving no way to finish. Itemised rather than
# guessed as one number, and deliberately generous:
#
#   panel padding (20 top + 20 bottom)                        40
#   Column spacing MD, title->body and body->actions        2*16
#   title (H3, 18px)                                          30
#   action row (compact PulseButton, 28 + slack)              36
#   AlertDialog's inset margin, top + bottom                   48
_DIALOG_FIXED_CHROME = 186

# One table's surroundings in "Name this payee": a single lead line, a
# single form row, and the table's own border.
#
#   lead line + the spacings around it and the spacer         52
#   the form row (label + field)                              80
#   DataTable's own border/padding outside ``scroll_height``   30
_GROUP_TABLE_CHROME = 162

# One GROUP's surroundings in "Make recurring", which is a different
# shape: it repeats a form row, a stack of lead lines, and a whole table
# for every group. Reusing the single-table number here under-counted the
# lead lines and, with more than one group, handed each table the entire
# window.
#
#   the form row (name + amount + category)                   80
#   four lead lines (facts, roll-up, separate-bill, untick)  4*32
#   DataTable's own border/padding outside ``scroll_height``   30
_DECLARE_GROUP_CHROME = 238

# What "Name this payee" needs for everything that is not its table.
_GROUP_DIALOG_CHROME = _DIALOG_FIXED_CHROME + _GROUP_TABLE_CHROME
# Floor, for a window too short to honour any of this.
_GROUP_TABLE_MIN_HEIGHT = 200


def _group_columns() -> list[DataTableColumn]:
    """Column layout for a payee-group table - shared by the No payee tab
    and the confirm dialog so the two can't drift into showing different
    facts about the same rows."""
    return [
        DataTableColumn("Count", width=90, alignment="right"),
        DataTableColumn("Looks like", hideable=False),
        DataTableColumn("Total", width=130, alignment="right"),
    ]


def _group_rows(groups: list[dict]) -> list[list[ft.Control]]:
    """Cells for ``_group_columns``."""
    return [
        [
            TableCellText(f"{g.get('count', 0):,}"),
            TableNameText(g.get("sample") or g.get("key", "")),
            _amount_cell(g.get("total_amount", 0)),
        ]
        for g in groups
    ]


def _declare_body_height(
    groups: int, table_height: int, page_height: float | None
) -> int:
    """Height for the Make recurring body, so the actions cannot clip.

    ``_group_table_height`` sizes each table against an ESTIMATE of the
    chrome around it, and an estimate can be wrong: too many lead lines,
    a window shorter than one group block, more groups than the window
    can seat at any size. Bounding the body means none of that reaches
    the action row - the worst case is a scrollbar, not a dialog you
    cannot finish.

    Sized to the content when the content fits, so the common case shows
    whole with no scrollbar at all.
    """
    content = groups * (table_height + _DECLARE_GROUP_CHROME)
    available = int((page_height or 900) - _DIALOG_FIXED_CHROME)
    return max(0, min(content, available))


def _group_table_height(
    row_count: int,
    page_height: float | None,
    *,
    tables: int = 1,
    table_chrome: int = _GROUP_TABLE_CHROME,
) -> int:
    """Fit the table to its rows, bounded only by the actual window.

    ``DataTable`` has no intrinsic height - it virtualizes against an
    explicit one - so this number decides whether the list shows whole or
    scrolls. A fixed cap gets that wrong in both directions: too small and
    a 12-row sweep scrolls on a tall screen for no reason, too large and
    the form fields fall off the bottom on a short one. So the ceiling is
    whatever the window has left after the dialog's chrome, and the table
    takes the smaller of that and what its rows actually need.

    ``tables`` is how many of these the dialog stacks, and each one SHARES
    the window rather than claiming it: "Make recurring" repeats a whole
    group block per bill. ``table_chrome`` is what one block costs around
    its table, which differs per dialog - passing the wrong one is how the
    action row got clipped.
    """
    header_and_padding = 56
    wanted = row_count * _DENSE_ROW_HEIGHT + header_and_padding
    fixed = int((page_height or 900) - _DIALOG_FIXED_CHROME)
    available = fixed // max(1, tables) - table_chrome
    # ``available`` is the hard ceiling in every branch, the floor
    # included: a floor that outranked it would clip the action row again
    # on a short window, which is the failure this whole function exists
    # to prevent. On a window that cannot even seat the floor, a cramped
    # table beats an unfinishable dialog.
    return max(0, min(max(_GROUP_TABLE_MIN_HEIGHT, wanted), available))


async def create_category(api, name: str) -> tuple[str, str] | None:
    """POST a new category and return its ``(id, name)`` for a picker.

    The endpoint is get-or-create, so a spacing or case variant of an
    existing category comes back as that category rather than a second
    one - which is what makes offering this inline safe at all. The name
    returned is the one that was STORED, which may differ from what was
    typed (a third path segment folds back to two), so callers should
    show this rather than the input.

    ``None`` on failure, matching APIClient's "never raises" contract.
    """
    created = await api.post("/api/v1/finance/categories", json={"name": name})
    if not isinstance(created, dict) or not created.get("id"):
        return None
    return str(created["id"]), str(created.get("name") or name)


async def apply_category_picks(api, picks: list[tuple[int, int]]) -> list[int]:
    """POST ``/transactions/{id}/categorize`` for each ``(transaction_id,
    category_id)`` pair, tolerating individual failures - shared by
    UncategorizedPanel's staged Save (which also needs to know WHICH
    pending rows actually cleared, to splice them out locally) and the
    Accounts register's instant bulk-recategorize (which only needs the
    count, via ``len()``), so the POST loop and APIClient's "None means
    failed, it never raises" contract (app/core/client.py) exist in one
    place instead of two copies drifting apart.
    """
    saved: list[int] = []
    for transaction_id, category_id in picks:
        result = await api.post(
            f"/api/v1/finance/transactions/{transaction_id}/categorize",
            json={"category_id": category_id},
        )
        if result is not None:
            saved.append(transaction_id)
    return saved


class NoPayeePanel(FinancePanel):
    """A work queue for transactions nobody has named a payee for.

    Deliberately leaner than ``UncategorizedPanel``: there is no
    pending/Save staging and no per-row suggestion to accept or reject,
    because a payee has no equivalent of the categorizer's guess - either
    you have told the app who this is or you haven't. Assign applies
    immediately, the same way the register's payee cell does.

    It also skips the register's "also apply to N similar" sweep on
    purpose: in a queue that is BY DEFINITION the unnamed rows, searching
    a payee and bulk-selecting the matches IS that sweep, done with your
    eyes on the actual list instead of a heuristic's guess at it.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        self._items: list[dict] = []
        # Server-reported total, which is NOT len(self._items): this queue
        # starts in the tens of thousands on a real import, so the table
        # shows a bounded page and the header states the honest number.
        self._total = 0
        # "groups" collapses the backlog by payee key so one decision
        # settles a thousand rows; "rows" is the raw list for the cases
        # where you need to see individual transactions.
        self._mode = "groups"
        self._groups: list[dict] = []
        self._active_group: dict | None = None
        self._merchants: list[tuple[str, str]] = []
        self._account_names: dict[int, str] = {}
        self._selected: set[int] = set()
        # Group mode selects KEYS, not row ids - a group is a descriptor
        # shape, not a transaction. Kept separate from ``_selected`` rather
        # than overloaded, because the two modes act through different
        # endpoints (ids -> assign-merchant, keys -> payee-groups/assign).
        self._selected_keys: set[str] = set()
        self._group_total = 0
        self._group_txn_total = 0
        self._query = ""
        self._debounce = Debouncer(page)
        self._header = SecondaryText("Loading…")
        self._body = ft.Container()
        self._search = FormTextField(
            label="Search payee",
            on_change=self._on_search_change,
            on_submit=self._on_search_submit,
            width=280,
            compact=True,
            clearable=True,
        )
        self._merchant_picker = MerchantPickerButton(
            merchants=self._merchants,
            on_pick=self._pick_merchant,
            on_create=self._create_merchant,
        )
        self._selection_label = SecondaryText("", visible=False)
        self._bulk_trigger = BulkActionTrigger(
            on_tap=self._open_bulk,
            label="Set payee",
            tooltip="Assign the same payee to every checked row at once",
        )
        self._tags: list[tuple[str, str]] = []
        self._tag_picker = TagPickerButton(
            tags=self._tags,
            on_pick=self._apply_tag,
            on_create=self._apply_tag,
        )
        self._bulk_tag_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_tag,
            label="Tag",
            tooltip="Put a tag on every checked row at once",
        )
        self._mode_button = PulseButton(
            on_click_callable=self._toggle_mode,
            text="View rows",
            variant="muted",
            compact=True,
        )
        # Indeterminate (value=None -> looping, not a fake percentage):
        # naming a group is ONE request/response, so there's no honest
        # fraction to report - the work is a single server-side UPDATE
        # over rows the client never sees. Same treatment (and same
        # reasoning) as Auto-categorize on the Uncategorized queue.
        self._progress = ft.ProgressBar(
            value=None,
            color=Theme.Colors.ACCENT,
            bgcolor=ft.Colors.with_opacity(0.15, Theme.Colors.ACCENT),
            visible=False,
        )
        self.content = ft.Column(
            [
                self._header,
                ft.Row(
                    [
                        self._search,
                        # A Container, not the bar itself: it keeps claiming
                        # this flex space regardless of visible=True/False,
                        # so the controls to its right don't jump sideways
                        # when the bar appears.
                        ft.Container(
                            content=self._progress,
                            expand=True,
                            alignment=ft.alignment.center,
                        ),
                        self._selection_label,
                        self._bulk_trigger,
                        self._bulk_tag_trigger,
                        self._mode_button,
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                self._body,
                self._merchant_picker,
                self._tag_picker,
            ],
            spacing=Theme.Spacing.MD,
            tight=True,
        )

    def refresh(self) -> None:
        if self.page:
            self.page.run_task(self._load)

    def _on_account_filter_change(self) -> None:
        # Debounced override: a rapid filter toggle must coalesce
        # into one refetch of a queue this large.
        self._debounce.run_now(self._load)

    def _on_search_change(self, event: ft.ControlEvent) -> None:
        self._query = (getattr(event.control, "value", "") or "").strip()
        self._debounce.schedule(self._load)

    def _on_search_submit(self, event: ft.ControlEvent) -> None:
        self._query = (getattr(event.control, "value", "") or "").strip()
        self._debounce.run_now(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._selected.clear()
        self._update_selection_label()
        self._set_busy(True)
        merchants = await api.get("/api/v1/finance/merchants")
        items = merchants.get("items", []) if isinstance(merchants, dict) else []
        self._merchants = [(str(m["id"]), m["name"]) for m in items]
        self._merchant_picker.update_merchants(self._merchants)
        self._tags = await fetch_tag_options(api)
        self._tag_picker.update_tags(self._tags)
        if not self._account_names:
            accounts = await api.get(
                "/api/v1/finance/accounts", params={"page_size": 200}
            )
            self._account_names = {
                a["id"]: a.get("name", "Account")
                for a in (
                    accounts.get("items", []) if isinstance(accounts, dict) else []
                )
            }

        if self._account_filter.is_empty:
            self._items, self._total = [], 0
        else:
            params: dict[str, object] = {
                "without_merchant": True,
                "page_size": _NO_PAYEE_PAGE_SIZE,
                **self._account_filter.params(),
            }
            if self._query:
                params["q"] = self._query
            data = await api.get("/api/v1/finance/transactions", params=params)
            self._items = data.get("items", []) if isinstance(data, dict) else []
            self._total = (
                data.get("total", len(self._items))
                if isinstance(data, dict)
                else len(self._items)
            )
            groups = await api.get(
                "/api/v1/finance/payee-groups", params={"limit": 300}
            )
            self._groups = groups.get("items", []) if isinstance(groups, dict) else []
            # Totals for the WHOLE backlog, not this page - the header used
            # to report len(self._groups), which is just the limit above.
            self._group_total = (
                groups.get("total", len(self._groups))
                if isinstance(groups, dict)
                else 0
            )
            self._group_txn_total = (
                groups.get("total_transactions", 0) if isinstance(groups, dict) else 0
            )
        self._set_busy(False)
        self._render()

    def _render(self) -> None:
        self._mode_button.text = (
            "View rows" if self._mode == "groups" else "View groups"
        )
        if self._mode_button.page:
            self._mode_button.update()
        if self._mode == "groups":
            self._render_groups()
            return
        shown, total = len(self._items), self._total
        if not total:
            self._header.value = (
                "No matches." if self._query else "Every transaction has a payee."
            )
        elif shown < total:
            self._header.value = (
                f"{total:,} transactions with no payee · showing the first "
                f"{shown:,}. Search a payee to narrow it down."
            )
        else:
            self._header.value = (
                f"{total:,} transaction{'s' if total != 1 else ''} with no payee"
            )
        columns = [
            DataTableColumn("Date", width=110),
            DataTableColumn("Account", width=200, style="secondary"),
            DataTableColumn("Payee", hideable=False),
            DataTableColumn("Amount", width=130, alignment="right"),
        ]
        rows = [
            [
                date_cell(t.get("date")),
                TableCellText(self._account_names.get(t.get("account_id"), "—")),
                TableNameText(t.get("name") or ""),
                _amount_cell(t.get("amount", 0)),
            ]
            for t in self._items
        ]

        def _on_selection(indices: set[int]) -> None:
            self._selected = {
                self._items[i]["id"] for i in indices if i < len(self._items)
            }
            self._update_selection_label()

        def _expand(idx: int) -> ft.Control:
            return _transaction_expanded_content(self._items[idx])

        self._body.content = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=560,
            selectable=True,
            on_selection_change=_on_selection,
            expandable_content=_expand,
            empty_message="Nothing left without a payee.",
        )
        if self.page:
            self.update()

    def _set_busy(self, busy: bool) -> None:
        """Show the working indicator. Covers the whole cycle - the write
        AND the reload behind it - because on this queue the reload is the
        slower half (it re-reads every payee-less row to rebuild the
        groups), and a bar that stops before the list refreshes would be
        lying about when the work is done."""
        self._progress.visible = busy
        if self._progress.page:
            self._progress.update()

    def _toggle_mode(self) -> None:
        self._mode = "rows" if self._mode == "groups" else "groups"
        self._selected.clear()
        self._selected_keys.clear()
        self._update_selection_label()
        self._render()

    def _render_groups(self) -> None:
        query = self._query.casefold()
        # Match the SAMPLE as well as the key: the key is the normalized
        # first few tokens, so searching "door" against keys alone misses
        # "BT*DD *DOORDASH ..." and "VENMO *DOORDASH ..." - exactly the
        # variants a brand sweep is trying to round up.
        groups = [
            g
            for g in self._groups
            if not query
            or query in g.get("key", "").casefold()
            or query in (g.get("sample") or "").casefold()
        ]
        covered = sum(g.get("count", 0) for g in groups)
        self._header.value = self._groups_header(len(groups), covered)
        columns = _group_columns()
        rows = _group_rows(groups)

        def _open_group(idx: int, _groups: list = groups) -> None:
            self._open_group_dialog([_groups[idx]])

        def _on_selection(indices: set[int], _groups: list = groups) -> None:
            self._selected_keys = {
                _groups[i].get("key", "") for i in indices if i < len(_groups)
            } - {""}
            self._update_selection_label()

        # Re-check whatever is still on screen after a re-render (a search
        # narrows the list; the boxes you already ticked should survive it).
        keep = [
            i for i, g in enumerate(groups) if g.get("key", "") in self._selected_keys
        ]
        self._body.content = DataTable(
            columns=columns,
            rows=rows,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=560,
            selectable=True,
            selected_indices=keep,
            on_selection_change=_on_selection,
            on_row_click=_open_group,
            empty_message="Nothing left without a payee.",
        )
        if self.page:
            self.update()

    def _groups_header(self, shown: int, covered: int) -> str:
        """Say what is actually true about the backlog.

        This line used to read "{transactions} with no payee, in {groups}
        groups" from two different populations: the transaction count came
        from /transactions (narrowed by the account filter AND the search
        box) while the group count was len(page) - i.e. the request limit,
        reporting "300 groups" when there were 2,436. Both numbers now come
        from /payee-groups, which counts the whole backlog.
        """
        if not self._groups:
            return "Every transaction has a payee."
        total_groups = self._group_total or len(self._groups)
        line = f"{self._group_txn_total:,} with no payee, in {total_groups:,} groups."
        if shown < total_groups:
            line += f" Showing {shown:,}, settling {covered:,}."
        else:
            line += f" Naming them all settles {covered:,}."
        return line

    def _open_group_dialog(self, groups: list[dict]) -> None:
        """Name one group, or every checked group at once. A dialog rather
        than the anchored picker: this settles up to a thousand
        transactions at once, so it deserves a deliberate confirm - and
        DataTable's row click carries no tap coordinates for the popup to
        anchor to anyway.

        The name is pre-filled from the key but fully editable, because the
        key is a descriptor, not a brand: "MCDONALD S" wants fixing to
        "McDonald's", and "NON CHASE ATM WITHDRAW" is not a merchant at all
        (Cancel is the right answer there).

        For a MULTI-group sweep the prefill is dropped: the whole point is
        that the descriptors disagree ("DOORDASH*CROWN FRIEDSAN..." vs
        "BT*DD *DOORDASH MCDOSAN..."), so any one of their suggested names
        would be an arbitrary pick presented as a default. The samples are
        listed instead, and you type the brand once.
        """
        if not groups:
            return
        count = sum(g.get("count", 0) for g in groups)
        name_field = FormTextField(
            label="Payee name",
            value=groups[0].get("suggested_name", "") if len(groups) == 1 else "",
            width=300,
        )
        # Optional, and only worth filling when the guess would miss. The
        # icon lookup otherwise tries "<name>.com", which cannot reach a
        # different TLD ("aegis-stack.io"), cannot keep punctuation that
        # was part of the name ("Aegis Stack" -> "aegisstack"), and can
        # land confidently on somebody else's site.
        website_field = FormTextField(
            label="Website (optional)",
            hint="aegis-stack.io - only needed if the logo looks wrong",
            width=300,
        )
        # Attaching to an EXISTING payee is the other half: these
        # descriptors often belong to a payee you already created.
        existing = ft.Dropdown(
            options=[ft.dropdown.Option(key=k, text=t) for k, t in self._merchants],
            enable_filter=True,
            enable_search=True,
            dense=True,
            width=300,
            hint_text="…or attach to an existing payee",
            border_radius=Theme.Components.INPUT_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            border_color=ft.Colors.OUTLINE,
            focused_border_color=Theme.Colors.PRIMARY,
            text_size=13,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=6),
            menu_height=240,
        )

        async def _close() -> None:
            dialog.open = False
            self.page.update()

        from app.components.frontend.state.session_state import get_session_state

        async def _confirm() -> None:
            payload: dict[str, object] = {
                "keys": [g.get("key", "") for g in groups if g.get("key")]
            }
            if existing.value:
                payload["merchant_id"] = int(existing.value)
            else:
                typed = (name_field.value or "").strip()
                if not typed:
                    ErrorSnackBar("Give the payee a name.").launch(self.page)
                    return
                payload["name"] = typed
            site = (website_field.value or "").strip()
            if site:
                payload["website_url"] = site
            dialog.open = False
            self.page.update()
            self._set_busy(True)
            try:
                result = await get_session_state(self.page).api_client.post(
                    "/api/v1/finance/payee-groups/assign", json=payload
                )
                if not isinstance(result, dict):
                    ErrorSnackBar(
                        "Could not name that group."
                        if len(groups) == 1
                        else "Could not name those groups."
                    ).launch(self.page)
                    return
                SuccessSnackBar(
                    f"Payee set on {result.get('updated', 0):,} transactions."
                ).launch(self.page)
                # These keys are settled - they no longer exist in the
                # backlog, so carrying the ticks over would re-apply to
                # whatever slid into those row positions.
                self._selected_keys.clear()
                self._update_selection_label()
                await self._load()
            finally:
                # finally: an API error must not leave the bar spinning
                # forever with no way back.
                self._set_busy(False)

        # The full table, not a sample of it: this is the confirm step for
        # a write that can settle thousands of transactions, so every row
        # it touches has to be visible and checkable - with its count and
        # its total, the two numbers that say whether a descriptor really
        # belongs to this payee. Same columns as the tab behind it.
        preview = DataTable(
            columns=_group_columns(),
            rows=_group_rows(groups),
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            scroll_height=_group_table_height(
                len(groups), getattr(self.page, "height", None)
            ),
        )
        lead = (
            f"{count:,} transaction{'s' if count != 1 else ''} look like this one:"
            if len(groups) == 1
            else (
                f"{len(groups):,} groups, {count:,} transactions. "
                "They all get this payee:"
            )
        )
        dialog = StyledAlertDialog(
            title="Name this payee" if len(groups) == 1 else "Name these payees",
            body=ft.Column(
                [
                    SecondaryText(lead),
                    preview,
                    ft.Container(height=Theme.Spacing.SM),
                    # One row, not a stack. Three 300px fields in a 980px
                    # dialog left two thirds of the width empty while
                    # costing ~140px of height - height being the scarce
                    # dimension here, since the panel clips (HARD_EDGE)
                    # rather than shrinks when it outgrows the window, and
                    # what gets clipped is the action row at the bottom.
                    ft.Row(
                        [name_field, website_field, existing],
                        spacing=Theme.Spacing.MD,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_confirm,
                    text=f"Name {count:,}",
                    variant="teal",
                    compact=True,
                ),
            ],
            # Wide enough for the descriptors to read whole. They run to
            # ~100 characters ("DOORDASH DASHPASS SAN FRANCISCO MARISA
            # BEDNER-14013-NT_MKD9OUT0 +16506819470"), and the tail is
            # often the only thing distinguishing two rows - ellipsizing
            # it defeats the point of showing the table.
            width=980,
        )
        self.page.open(dialog)

    def _update_selection_label(self) -> None:
        # Both modes select; they just select different things. Rows count
        # transactions, groups count groups - and the label says which, so
        # "12 selected" can't be misread as 12 transactions when it is 12
        # descriptor shapes covering hundreds.
        if self._mode == "rows":
            count = len(self._selected)
            label = f"{count} selected"
        else:
            count = len(self._selected_keys)
            covered = sum(
                g.get("count", 0)
                for g in self._groups
                if g.get("key", "") in self._selected_keys
            )
            label = f"{count:,} groups · {covered:,} transactions"
        self._selection_label.value = label if count else ""
        self._selection_label.visible = bool(count)
        if self._selection_label.page:
            self._selection_label.update()
        self._bulk_trigger.set_count(count)
        self._bulk_tag_trigger.set_count(count if self._mode == "rows" else 0)

    def _open_bulk_tag(self, e: ft.ControlEvent) -> None:
        # Rows mode only: a group selection is descriptor KEYS, not
        # transaction ids, and the tag endpoint speaks ids.
        if self._mode == "rows" and self._selected:
            self._tag_picker.open_for(list(self._selected), e)

    def _apply_tag(self, transaction_ids: list[int], name: str) -> None:
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_tag_async, transaction_ids, name.strip())

    async def _apply_tag_async(self, transaction_ids: list[int], name: str) -> None:
        if await post_tag(self.page, transaction_ids, name):
            await self._load()

    def _open_bulk(self, e: ft.ControlEvent) -> None:
        if self._mode == "rows":
            if self._selected:
                self._merchant_picker.open_for(list(self._selected), e)
            return
        # Groups go through the dialog, not the anchored picker: this can
        # settle thousands of transactions in one click, and the dialog is
        # where naming a NEW payee (with an optional website for the logo)
        # lives. Same reasoning as the single-group row click.
        selected = [g for g in self._groups if g.get("key", "") in self._selected_keys]
        if selected:
            self._open_group_dialog(selected)

    def _pick_merchant(self, transaction_ids: list[int], merchant_key: str) -> None:
        if merchant_key and transaction_ids and self.page:
            self.page.run_task(self._apply, transaction_ids, int(merchant_key))

    def _create_merchant(self, transaction_ids: list[int], name: str) -> None:
        if name and transaction_ids and self.page:
            self.page.run_task(self._create_and_apply, transaction_ids, name)

    async def _create_and_apply(self, transaction_ids: list[int], name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await api.post("/api/v1/finance/merchants", json={"name": name})
        if not isinstance(created, dict) or created.get("id") is None:
            ErrorSnackBar(f'Could not create the payee "{name}".').launch(self.page)
            return
        await self._apply(transaction_ids, int(created["id"]))

    async def _apply(self, transaction_ids: list[int], merchant_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            result = await api.post(
                "/api/v1/finance/transactions/assign-merchant",
                json={"transaction_ids": transaction_ids, "merchant_id": merchant_id},
            )
            if not isinstance(result, dict):
                ErrorSnackBar("Could not set the payee.").launch(self.page)
                return
            updated = result.get("updated", 0)
            SuccessSnackBar(
                f"Payee set on {updated} transaction{'s' if updated != 1 else ''}."
            ).launch(self.page)
            await self._load()
        finally:
            self._set_busy(False)


class UncategorizedPanel(FinancePanel):
    """A work queue for uncategorized transactions, not a report. Two
    consumers share this one class rather than duplicating it: the
    Overview card's dialog (``OverviewTab._open_uncategorized``, fixed
    ``width``) and an embedded section on ``ReviewTab`` (``width=None``,
    fills the tab instead). Each owns its own instance and data load -
    they don't share row/pending/suggestion state. They CAN share the
    ``AccountFilter`` selection (``account_filter``) and, when
    ``register_filter_listener`` is given (the ReviewTab case - a shared
    button already lives above FinanceDetailDialog's tab strip), even
    the filter BUTTON itself; the standalone popup case builds its own
    (see the constructor for why - that button would otherwise be
    unreachable behind the popup).

    Rows render through ``DataTable`` (controls/data_table.py) with
    ``scroll_height`` set, same as the account register at :1540 - that
    puts rows in a ``ft.ListView`` under the hood, so only the rows
    actually on screen get built. A plain ``ft.Column`` (the first version
    of this panel) mounts every row's full widget tree immediately
    regardless of scroll position, which is what made it feel sluggish.

    Nothing is written on pick - review-then-save. A row moves through up
    to three states, all inline (no modal - the list stays visible and
    scrollable the whole time, unlike an earlier version that opened a
    dialog per row):

    - empty: "Tap to categorize" placeholder. Tap -> opens the shared
      ``CategoryPickerButton`` popup (``pickers.py``), positioned
      at that row (``_empty_cell``'s ``on_tap_down`` -> ``open_for``) -
      search-at-top, single-select, same popup mechanism
      ``AccountFilterButton`` already uses. One instance for the whole
      panel, not one per row: an earlier version put a live dropdown in
      EVERY row up front, which with a real category count (267 in
      testing) meant up to 100 rows x 267 options each, ~27,000 Option
      controls built and serialized on every load regardless of the
      ListView only PAINTING visible rows (building the full Python
      control tree eagerly is what made it slow, not the virtualization -
      confirmed by a side-by-side test with the dropdown stripped out,
      which was fast). The shared popup sidesteps that class of problem
      entirely - its option rows are built once, not per row.
    - suggested: Auto-categorize proposed a category for this row
      (``_suggested``) but nothing is saved yet - shows "Suggested: X"
      with an accept (check) and reject (x) affordance, so a suggestion
      can be individually disagreed with rather than accepted as a batch.
    - pending: a manual pick, or an accepted suggestion (``_pending``) -
      ready to save, with a clear (x) to unpick it. The header's Save
      button is disabled until at least one row is pending, and commits
      every pending row in one pass when clicked.

    Auto-categorize never clobbers a row that already has a pending pick
    or an unreviewed suggestion - it only proposes for rows still empty.

    Same reload-not-splice idiom as ReviewTab._action / AttentionTab._dismiss
    above for the actual save: POST each pending row -> SuccessSnackBar ->
    re-``GET /uncategorized``, so a row "disappears" because the next fetch
    no longer includes it (this also resets ``_pending``/``_suggested`` -
    unsaved picks don't survive a reload or the dialog closing). Refreshing
    the Overview card's own count (a separate, read-only preview - see
    ``OverviewTab._load``) is the dialog opener's job, once, on close - not
    this panel's.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        width: int | None = 860,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener)
        # Fixed width for the Overview card's dialog (StyledAlertDialog has
        # no viewport-relative sizing of its own); width=None for embedding
        # directly in a tab (ReviewTab), which already gives it the column's
        # width to fill. No expand=True either way: the content is already
        # height-bounded internally (scroll_height on the DataTable), so
        # claiming extra vertical flex would just take space away from
        # whatever else shares the column - the transfer suggestions list,
        # when embedded - without the panel itself using it.
        if width is not None:
            self.width = width
        self._categories: list[tuple[str, str]] = []
        self._account_names: dict[int, str] = {}
        # Raw list, kept alongside _account_names - _account_filter_button
        # .set_accounts() needs the full account dicts (for grouping), not
        # just the id->name map, and it has to be called on every load (a
        # filter change re-renders the menu's dots/trigger label too, not
        # just the table), while the accounts themselves only need
        # fetching once. Keeping this separately is what lets those two
        # things happen at different frequencies.
        self._account_items: list[dict] = []
        self._items: list[dict] = []
        # Last server-reported backlog size (not just len(self._items),
        # which can be a narrower page) - tracked so Save can update the
        # header after a local splice without a full server refetch.
        self._total = 0
        # transaction_id -> category_id, a manual pick or an accepted
        # suggestion, ready to save.
        self._pending: dict[int, int] = {}
        # transaction_id -> (category_id, category_name), an unreviewed
        # Auto-categorize proposal awaiting accept/reject.
        self._suggested: dict[int, tuple[int, str]] = {}
        # Checkbox selection (DataTable's ``selectable``) - transaction
        # ids, not the table's own row indices, so a selection survives
        # a sort/rebuild instead of pointing at whatever row happens to
        # land on that index next. Scopes Auto-categorize to "just these"
        # when non-empty; the full backlog otherwise, unchanged.
        self._selected: set[int] = set()
        self._ordered: list[dict] = []
        # One stable Container per currently-rendered row's category cell,
        # keyed by transaction id - a pick/accept/reject/clear swaps just
        # THAT container's content in place (_refresh_category_cell)
        # instead of rebuilding all ~900 rows for a single row's state
        # change. Repopulated fresh on every real _render_table() rebuild.
        self._category_cells: dict[int, ft.Container] = {}
        # One shared popup for every row's category cell - see
        # pickers.py's own docstring for why this is a single
        # instance opened via open_for(), not one CategoryPickerButton
        # built per row.
        self._category_picker = CategoryPickerButton(
            categories=self._categories,
            on_pick=self._pick_category,
            on_create=self._create_category,
        )
        self._selection_label = SecondaryText("", visible=False)
        self._bulk_categorize_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_categorize
        )
        self._tags: list[tuple[str, str]] = []
        self._tag_picker = TagPickerButton(
            tags=self._tags,
            on_pick=self._apply_tag,
            on_create=self._apply_tag,
        )
        # Applies immediately, unlike the category picks this queue
        # stages behind Save - a tag is an annotation, not a
        # classification you might want to review as a batch.
        self._bulk_tag_trigger = BulkActionTrigger(
            on_tap=self._open_bulk_tag,
            label="Tag",
            tooltip="Put a tag on every checked row at once",
        )
        self._header = SecondaryText("Loading…")
        self._body = ft.Container()
        # Same payee search as the Accounts register (TransactionsPanel,
        # :1096-1103) - same FormTextField + Debouncer wiring, same ``q``
        # param, same case-insensitive substring-on-name match server-side.
        self._query = ""
        self._debounce = Debouncer(page)
        self._search = FormTextField(
            label="Search payee",
            on_change=self._on_search_change,
            on_submit=self._on_search_submit,
            width=280,
            compact=True,
            clearable=True,
        )
        # Same trailing-window picker as the Accounts register (:1104-1122)
        # - the exact DateRangeChips control every range picker in the
        # product uses, not a bespoke one. Defaults to "All": this is a
        # work queue, not a historical register, and a narrower default
        # would silently hide backlog rows the same way the old 100-row
        # cap used to (see _UNCATEGORIZED_LOAD_LIMIT above).
        self._range_days = 9999
        self._range = DateRangeChips(
            options=[
                ("1d", 1),
                ("7d", 7),
                ("14d", 14),
                ("1m", 30),
                ("3m", 90),
                ("1y", 365),
                ("All", 9999),
            ],
            selected_days=self._range_days,
            on_change=self._on_range_change,
        )
        # Own account-filter BUTTON only when standalone (the Overview
        # card's popup, OverviewTab._open_uncategorized) - when embedded
        # as a tab (ReviewTab), FinanceDetailDialog already shows ONE
        # shared button above the tab strip, and building a second one
        # here duplicated UI over the same AccountFilter with no way to
        # keep both in sync (confirmed live: changing one left the
        # other's dots/trigger label stale - see FinanceDetailDialog's
        # own docstring on this). register_filter_listener being given at
        # all is what signals "a shared button already covers this."
        self._account_filter_button: AccountFilterButton | None = None
        if register_filter_listener is None:
            self._account_filter_button = AccountFilterButton(
                on_change=self._on_account_filter_change,
                account_filter=account_filter,
            )
            # Standalone: the button owns the filter, replacing the
            # base's default. Embedded (listener given), the base
            # already adopted the shared filter and registered the
            # reload.
            self._account_filter = self._account_filter_button.filter
        # Indeterminate (value=None -> looping, not a fake percentage - the
        # sweep is one request/response, there's no real progress fraction
        # to report) - shown only while Auto-categorize is in flight. Same
        # teal as the tab indicator (Theme.Colors.ACCENT, controls/tabs.py).
        self._progress = ft.ProgressBar(
            value=None,
            color=Theme.Colors.ACCENT,
            bgcolor=ft.Colors.with_opacity(0.15, Theme.Colors.ACCENT),
            visible=False,
        )
        self._save_button = PulseButton(
            on_click_callable=self._save_pending,
            text="Save",
            compact=True,
        )
        # Set after construction, not as a kwarg: PulseButton accepts
        # **kwargs but never forwards them to the Flet control, so
        # disabled=True was inert and Save looked clickable with nothing
        # staged until the first table render corrected it.
        self._save_button.disabled = True
        # None when a shared button above the tab strip already covers
        # this (see the constructor comment above).
        controls_row: list[ft.Control] = [self._search]
        if self._account_filter_button is not None:
            controls_row.append(self._account_filter_button)
        controls_row.append(self._range)
        self.content = ft.Column(
            [
                # On its own line: sharing a row with the search/filter
                # controls meant its own text length ("Nothing left to
                # categorize." vs "4 to review") shifted everything to its
                # right sideways every time the count changed.
                self._header,
                ft.Row(
                    [
                        *controls_row,
                        # A Container, not the ProgressBar directly: it
                        # keeps claiming this flex space regardless of the
                        # bar's own visible=True/False, so the buttons to
                        # its right don't jump sideways when the bar
                        # appears/disappears - only what's drawn inside
                        # this reserved gap changes.
                        ft.Container(
                            content=self._progress,
                            expand=True,
                            alignment=ft.alignment.center,
                        ),
                        self._selection_label,
                        self._bulk_categorize_trigger,
                        self._bulk_tag_trigger,
                        PulseButton(
                            on_click_callable=self._auto_categorize,
                            text="Auto-categorize",
                            variant="amber",
                            compact=True,
                            tooltip=(
                                "Scoped to the checked rows when any are "
                                "selected; the whole backlog otherwise"
                            ),
                        ),
                        self._save_button,
                    ],
                    spacing=Theme.Spacing.SM,
                    # END, not CENTER: _search is a FormTextField (a label
                    # ABOVE the input), everything else here is a single
                    # label-less line (chips, the filter button, buttons).
                    # Centering the whole row middles those against the
                    # label+input block's combined height, which reads as
                    # floating above the input rather than beside it - END
                    # lines their bottom edge up with the input's own.
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                self._body,
                # Zero-size: this is the shared category-picker popup's
                # OWN mount point, not part of the visible layout - see
                # its own docstring. Has to sit somewhere in the tree for
                # its did_mount to fire and register into page.overlay.
                self._category_picker,
                self._tag_picker,
            ],
            spacing=Theme.Spacing.MD,
            tight=True,
        )

    def refresh(self) -> None:
        """Public reload for a caller that keeps its own reference to a
        CACHED panel instance (``OverviewTab._open_uncategorized``) -
        ``did_mount`` only fires once, on first mount, so a cached
        panel's data would otherwise go stale after the first open."""
        if self.page:
            self.page.run_task(self._load)

    def _on_search_change(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        # Type-ahead: re-filters on its own once typing pauses, same as
        # the Accounts register - Enter becomes optional, not required.
        self._debounce.schedule(lambda: self._load(reset_state=False))

    def _on_search_submit(self, event: ft.ControlEvent) -> None:
        control = getattr(event, "control", None)
        self._query = (getattr(control, "value", "") or "").strip()
        self._debounce.run_now(lambda: self._load(reset_state=False))

    def _range_from(self) -> date | None:
        if self._range_days >= 9000:  # the "All" sentinel, per insights
            return None
        return date.today() - timedelta(days=self._range_days)

    def _on_range_change(self, days: int) -> None:
        self._range_days = days
        # Through the debouncer, not a raw page.run_task(lambda: ...) -
        # Page.run_task asserts its handler is an actual coroutine
        # function, which a lambda wrapping a call is not (see the
        # run_now fix in controls/debounce.py). Also correctly supersedes
        # an in-flight search debounce, same as pressing Enter would.
        self._debounce.run_now(lambda: self._load(reset_state=False))

    def _on_account_filter_change(self) -> None:
        self._debounce.run_now(lambda: self._load(reset_state=False))

    async def _load(self, *, reset_state: bool = True) -> None:
        """``reset_state=False`` for a search-, range-, or account-filter-
        triggered reload: the server response is a different SUBSET of
        the same backlog, not a fresh backlog - a pending pick or an
        unreviewed suggestion on a row that happens not to match the
        current search text, date range, or account selection is still
        real, unsaved work, and narrowing the view was wiping it. True
        fresh loads (initial mount, post-Save) keep clearing: that state
        genuinely doesn't apply to a new fetch there.
        """
        from app.components.frontend.state.session_state import get_session_state
        from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

        # Claim this run - two requests in flight can return out of
        # order, so a superseded one must not paint (same guard the
        # Accounts register uses around its own search).
        sequence = self._debounce.sequence
        api = get_session_state(self.page).api_client

        if not self._categories:
            cat_data = await api.get("/api/v1/finance/categories/options")
            cat_items = cat_data.get("items", []) if isinstance(cat_data, dict) else []
            self._categories = [
                (str(c["id"]), c["name"])
                for c in cat_items
                if str(c.get("name", "")).lower() not in UNCATEGORIZED_CATEGORY_NAMES
            ]
            self._category_picker.update_categories(self._categories)
        self._tags = await fetch_tag_options(api)
        self._tag_picker.update_tags(self._tags)

        if not self._account_names:
            acct_data = await api.get(
                "/api/v1/finance/accounts", params={"page_size": 200}
            )
            self._account_items = (
                acct_data.get("items", []) if isinstance(acct_data, dict) else []
            )
            self._account_names = {a["id"]: a["name"] for a in self._account_items}
        # Every load, not just the first fetch above: a filter change
        # (toggling one account, "Remove all") has to redraw the menu's
        # own dots/trigger label too, not just refilter the table below -
        # this was gated behind the fetch-once cache, so the menu stayed
        # stuck showing the state from whenever it first mounted while the
        # table underneath it kept correctly refiltering (confirmed live:
        # "Remove all" correctly emptied the table, but every dot in the
        # still-open menu stayed lit). None when a shared button above the
        # tab strip owns this instead (see the constructor).
        if self._account_filter_button is not None:
            self._account_filter_button.set_accounts(self._account_items)

        # An explicit empty selection ("Remove all") means literally
        # nothing, not "no filter" - AccountFilter.params() is never
        # called in this state (see its own docstring), so the fetch is
        # skipped outright instead, same as OverviewTab's own charts do.
        if self._account_filter.is_empty:
            if not self._debounce.is_current(sequence):
                return
            self._items = []
            self._total = 0
            if reset_state:
                self._pending.clear()
                self._suggested.clear()
                self._selected.clear()
            self._render_table()
            return

        params: dict[str, object] = {
            "limit": _UNCATEGORIZED_LOAD_LIMIT,
            **self._account_filter.params(),
        }
        if self._query:
            params["q"] = self._query
        from_date = self._range_from()
        if from_date is not None:
            params["from"] = from_date.isoformat()
        data = await api.get("/api/v1/finance/uncategorized", params=params)
        if not self._debounce.is_current(sequence):
            return  # a newer keystroke already owns this load
        self._items = data.get("items", []) if isinstance(data, dict) else []
        self._total = data.get("total", 0) if isinstance(data, dict) else 0
        if reset_state:
            self._pending.clear()
            self._suggested.clear()
            self._selected.clear()

        self._render_table()

    def _header_text(self) -> str:
        return (
            "Nothing left to categorize."
            if not self._items
            else f"Showing {len(self._items)} of {self._total:,}"
            if self._total > len(self._items)
            else f"{self._total:,} to review"
        )

    def _render_table(self) -> None:
        """Rebuild the table from in-memory state (no re-fetch) - called
        after a real data change (a load, a search, a save). A single
        row's pick/accept/reject/clear does NOT come through here - see
        ``_refresh_category_cell``, which swaps just that row's cell in
        place instead of rebuilding all ~900 rows for a one-row change.

        Also the single source of truth for the header text - both
        ``_load`` and ``_save_pending`` used to set it themselves before
        calling this, which was one more place for the two to drift.
        Every real state change ends up here, so this is the one spot
        that always has the freshest counts to hand.

        Suggested rows sort to the top - after Auto-categorize they'd
        otherwise be scattered wherever their transaction falls in normal
        date order, and the whole point of clicking that button is to
        review what it proposed, not hunt through the list for it.
        ``sorted`` is stable, so date order still holds within each group.
        A row accepted/rejected one at a time afterward stays put rather
        than re-sorting out from under the cursor - only a fresh sweep
        (Auto-categorize itself, which does call this) regroups them.
        This is just the NATURAL order though - clicking the Category
        header (or any other column's) overrides it via DataTable's own
        generic sort, same as every other column.
        """
        ordered = sorted(
            self._items, key=lambda txn: 0 if txn["id"] in self._suggested else 1
        )
        self._ordered = ordered
        self._category_cells = {}
        selected_indices = {
            i for i, txn in enumerate(ordered) if txn["id"] in self._selected
        }
        self._header.value = self._header_text()
        self._body.content = DataTable(
            columns=_UNCATEGORIZED_COLUMNS,
            rows=[self._row(item) for item in ordered],
            empty_message="No uncategorized transactions.",
            scroll_height=560,
            row_padding=6,
            item_extent=_DENSE_ROW_HEIGHT,
            selectable=True,
            selected_indices=selected_indices,
            on_selection_change=self._on_selection_change,
            # Same inline row-expand the Accounts register uses
            # (TransactionsPanel._load) - the checkbox and the category
            # cell each claim their own tap, so this only fires from the
            # rest of the row (date/payee/amount, or empty space), same as
            # any other Flet control nested in a row.
            expandable_content=self._expand_transaction_detail,
        )
        self._save_button.disabled = not self._pending
        self._update_selection_label()
        if self.page:
            self.update()

    def _expand_transaction_detail(self, idx: int) -> ft.Control:
        if idx >= len(self._ordered):
            return ft.Container()
        return _transaction_expanded_content(self._ordered[idx])

    def _on_selection_change(self, indices: set[int]) -> None:
        """DataTable's own checkbox toggling stays cheap (no table
        rebuild) by owning selection between renders itself - this just
        mirrors the result back into transaction ids, which survive
        across the NEXT rebuild (a pick, an accept/reject, a reload)
        where DataTable's own index-based state does not."""
        self._selected = {
            self._ordered[i]["id"] for i in indices if i < len(self._ordered)
        }
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        count = len(self._selected)
        self._selection_label.value = f"{count} selected" if count else ""
        self._selection_label.visible = bool(count)
        if self._selection_label.page:
            self._selection_label.update()
        self._bulk_categorize_trigger.set_count(count)
        self._bulk_tag_trigger.set_count(count)

    def _open_bulk_categorize(self, e: ft.ControlEvent) -> None:
        if self._selected:
            self._category_picker.open_for(list(self._selected), e)

    def _open_bulk_tag(self, e: ft.ControlEvent) -> None:
        if self._selected:
            self._tag_picker.open_for(list(self._selected), e)

    def _apply_tag(self, transaction_ids: list[int], name: str) -> None:
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_tag_async, transaction_ids, name.strip())

    async def _apply_tag_async(self, transaction_ids: list[int], name: str) -> None:
        if await post_tag(self.page, transaction_ids, name):
            await self._load()

    def _row(self, txn: dict) -> list[ft.Control]:
        name = txn.get("name") or txn.get("merchant_name") or "(no description)"
        account_name = self._account_names.get(txn.get("account_id"), "—")
        return [
            date_cell(txn.get("date")),
            # A plain string, not a pre-built SecondaryText - letting
            # DataTable's own style_cell() construct it is what gives it
            # the column's style="secondary" AND the single-line ellipsis
            # truncation style_cell applies; a hand-built control bypasses
            # both (style_cell passes any already-built control through
            # untouched).
            account_name,
            TableNameText(name),
            _amount_cell(txn.get("amount") or 0),
            self._category_cell(txn["id"]),
        ]

    def _category_cell(self, transaction_id: int) -> ft.Control:
        """A stable Container, tracked in ``self._category_cells`` -
        ``_refresh_category_cell`` swaps its content in place later
        without needing a full table rebuild to reach it."""
        container = ft.Container(content=self._category_cell_content(transaction_id))
        # DataTable's generic column sort reads a cell's .value (or
        # .content.value) for plain text; this cell is a Row of buttons,
        # not text, so .data carries the sortable name explicitly -
        # DataTable's _cell_text falls back to it. Flet's own generic
        # "attach arbitrary data to a control" field, not a new concept.
        container.data = self._category_sort_text(transaction_id)
        self._category_cells[transaction_id] = container
        return container

    def _category_cell_content(self, transaction_id: int) -> ft.Control:
        if transaction_id in self._pending:
            return self._pending_cell(transaction_id)
        if transaction_id in self._suggested:
            return self._suggested_cell(transaction_id)
        return self._empty_cell(transaction_id)

    def _category_sort_text(self, transaction_id: int) -> str:
        """Blank sorts last (DataTable treats "" as no value) - an
        untouched row has no category opinion yet, so it belongs after
        everything that does, in either sort direction."""
        if transaction_id in self._pending:
            return self._category_name(self._pending[transaction_id])
        if transaction_id in self._suggested:
            return self._suggested[transaction_id][1]
        return ""

    def _refresh_category_cell(self, transaction_id: int) -> None:
        """One row's state changed (pick/accept/reject/clear) - swap just
        that row's category cell content, not the whole ~900-row table."""
        container = self._category_cells.get(transaction_id)
        if container is not None:
            container.content = self._category_cell_content(transaction_id)
            container.data = self._category_sort_text(transaction_id)
            if container.page:
                container.update()
        self._save_button.disabled = not self._pending
        if self._save_button.page:
            self._save_button.update()

    def _empty_cell(self, transaction_id: int) -> ft.Container:
        """A cheap placeholder that opens the shared category-picker
        popup on tap - see ``pickers.py`` for why one popup is
        shared across every row instead of building one per cell, and
        ``category_trigger_cell``'s own docstring for why it's the width
        and the on_click no-op, not just on_tap_down, that make this
        reliably clickable."""
        return picker_trigger_cell(
            SecondaryText("Tap to categorize", size=Theme.Typography.CAPTION),
            _CATEGORY_COLUMN_WIDTH,
            on_tap=lambda e, t=transaction_id: self._category_picker.open_for([t], e),
        )

    def _pending_cell(self, transaction_id: int) -> ft.Control:
        name = self._category_name(self._pending[transaction_id])
        return ft.Row(
            [
                # expand=True: the text claims whatever's left after the
                # button's own fixed size and truncates (TableNameText's
                # own ellipsis default) INSIDE that space, instead of the
                # Row sizing to the text's full natural width first and
                # pushing the button out past the column's own edge - a
                # long category path ("Fees & Charges:Finance Charge")
                # was clipping the button clean off before this.
                ft.Container(
                    content=TableNameText(name),
                    expand=True,
                ),
                CompactIconButton(
                    ft.Icons.CLOSE,
                    ft.Colors.ON_SURFACE_VARIANT,
                    "Clear",
                    lambda _e, t=transaction_id: self._clear_pending(t),
                ),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _suggested_cell(self, transaction_id: int) -> ft.Control:
        _category_id, name = self._suggested[transaction_id]
        return ft.Row(
            [
                # Same expand=True reasoning as _pending_cell - two
                # buttons here instead of one, so there's even less
                # margin for the text to push them off the edge.
                ft.Container(
                    content=TableCellText(f"Suggested: {name}"),
                    expand=True,
                ),
                CompactIconButton(
                    ft.Icons.CHECK,
                    Theme.Colors.SUCCESS,
                    "Accept",
                    lambda _e, t=transaction_id: self._accept_suggestion(t),
                ),
                CompactIconButton(
                    ft.Icons.CLOSE,
                    Theme.Colors.ERROR,
                    "Reject",
                    lambda _e, t=transaction_id: self._reject_suggestion(t),
                ),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _category_name(self, category_id: int) -> str:
        key = str(category_id)
        for k, name in self._categories:
            if k == key:
                return name
        return f"Category {category_id}"

    def _pick_category(self, transaction_ids: list[int], category_key: str) -> None:
        """CategoryPickerButton's on_pick contract - a single row's pick
        and a bulk "categorize the selected rows" pick are the same call,
        just with a longer list (see pickers.py's own docstring).
        Stages the pick(s) - does not save."""
        if not category_key:
            return
        category_id = int(category_key)
        for transaction_id in transaction_ids:
            self._pending[transaction_id] = category_id
            self._suggested.pop(transaction_id, None)
            self._refresh_category_cell(transaction_id)

    def _create_category(self, transaction_ids: list[int], name: str) -> None:
        """Name a category, then STAGE it on the rows - this panel saves
        on its own Save button, and creating one must not quietly become
        the exception that writes immediately."""
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._create_and_stage, transaction_ids, name)

    async def _create_and_stage(self, transaction_ids: list[int], name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await create_category(api, name)
        if created is None:
            ErrorSnackBar("Could not create that category.").launch(self.page)
            return
        key, stored = created
        if key not in {k for k, _ in self._categories}:
            self._categories = sorted(
                [*self._categories, (key, stored)], key=lambda c: c[1].casefold()
            )
            self._category_picker.update_categories(self._categories)
        self._pick_category(transaction_ids, key)
        self.page.update()

    def _clear_pending(self, transaction_id: int) -> None:
        self._pending.pop(transaction_id, None)
        self._refresh_category_cell(transaction_id)

    def _accept_suggestion(self, transaction_id: int) -> None:
        suggestion = self._suggested.pop(transaction_id, None)
        if suggestion is not None:
            self._pending[transaction_id] = suggestion[0]
        self._refresh_category_cell(transaction_id)

    def _reject_suggestion(self, transaction_id: int) -> None:
        self._suggested.pop(transaction_id, None)
        self._refresh_category_cell(transaction_id)

    async def _auto_categorize(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        self._progress.visible = True
        if self.page:
            self.update()

        scope = set(self._selected)  # snapshot - cleared below before the render
        api = get_session_state(self.page).api_client
        body = {"transaction_ids": list(scope)} if scope else {}
        result = await api.post(
            "/api/v1/finance/transactions/auto-categorize", json=body
        )
        self._progress.visible = False
        if self.page:
            self.update()
        suggestions = result.get("items", []) if isinstance(result, dict) else []
        added = 0
        for s in suggestions:
            txn_id = s.get("transaction_id")
            # Don't clobber a row the user already picked or already has
            # an unreviewed suggestion on.
            if txn_id is None or txn_id in self._pending or txn_id in self._suggested:
                continue
            self._suggested[txn_id] = (s["category_id"], s.get("category_name") or "")
            added += 1
        scoped_note = f" from {len(scope):,} selected" if scope else ""
        SuccessSnackBar(
            f"{added} suggestion{'s' if added != 1 else ''} ready to review"
            f"{scoped_note}."
            if added
            else "No new suggestions - nothing had a clear category precedent yet."
        ).launch(self.page)
        self._selected.clear()
        # A real rebuild here on purpose (unlike a single accept/reject):
        # this is what re-sorts newly-suggested rows to the top, the
        # whole point of clicking this button being able to review what
        # it proposed without hunting for it in 900 date-sorted rows.
        # Tried skipping this for speed (in-place per-cell updates,
        # keeping rows in place) - lost the grouping, which mattered
        # more than the speed here. Reverted.
        self._render_table()

    async def _save_pending(self) -> None:
        if not self._pending:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        to_save = list(self._pending.items())
        saved_ids = await apply_category_picks(api, to_save)
        failed = len(to_save) - len(saved_ids)
        message = (
            f"Saved {len(saved_ids)}."
            if not failed
            else f"Saved {len(saved_ids)}, {failed} failed."
        )
        (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)

        # A saved row disappears immediately - tried leaving it visible
        # with a "Saved" confirmation to skip the rebuild below entirely,
        # but that's not what was wanted: hitting Save should remove the
        # row, not leave it lingering until the next reload. Reverted.
        #
        # Still no re-``GET /uncategorized`` though - the POST results
        # above already say exactly which rows just left the backlog, so
        # splicing locally and rebuilding once (no network round trip)
        # is the honest middle ground: correct behavior, still cheaper
        # than the original refetch-then-rebuild.
        saved = set(saved_ids)
        for transaction_id, _ in to_save:
            self._pending.pop(transaction_id, None)
        if saved:
            self._items = [t for t in self._items if t["id"] not in saved]
            self._selected -= saved
            self._total = max(self._total - len(saved), 0)
        self._render_table()


def _budget_status_color(status: str) -> str:
    """Maps the backend's ``good``/``warn``/``critical`` (see
    ``_budget_line_status`` in finance_service.py) straight to a theme
    color - the 80%/100% thresholds are computed once, server-side; the
    frontend never recomputes them from raw numbers."""
    return {
        "critical": Theme.Colors.ERROR,
        "warn": Theme.Colors.WARNING,
    }.get(status, Theme.Colors.SUCCESS)


def dollars_to_cents(raw: str | None) -> int | None:
    """ "$1,200.50" / "3,000" / " 12 " -> cents; junk -> None."""
    text = (raw or "").replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return round(float(text) * 100)
    except ValueError:
        return None


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


_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


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


class BudgetPanel(FinancePanel):
    """Budget tab: a natural-language goal box, a 4-cell stats strip, then
    three sections.

    Fixed/Non-monthly are detected recurring commitments shown for
    CONTEXT ONLY - an earlier version gave every one of them (including
    the mortgage) a spend-vs-allocation status the same as a real budget
    line, which read as "you're over budget on your own mortgage". These
    read a variance-vs-last-month signal instead (``status_dot``, never
    critical) and have no remove/edit action - that's Bills & Income's
    job. Flexible is the actual budget: limits chosen by category or
    payee, by typed goal or by hand, each with a real spend-vs-allocation
    status and a remove action.

    The goal box mirrors ``UncategorizedPanel``'s review-before-commit
    shape: ``POST /budget/goal`` only computes a suggestion (accept/reject
    row, same interaction as ``_suggested_cell``); accepting it is a
    separate ``POST /budget/lines`` call, same split as auto-categorize's
    suggest-then-apply.
    """

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener, expand=True)
        self._categories: list[tuple[str, str]] = []
        self._summary: dict[str, Any] | None = None
        # One shared popup for all five cells (see StatDetailPopup), and
        # one fetch of the per-row details behind it - cleared per load
        # so it always matches what the cells show.
        self._stat_detail = StatDetailPopup()
        self._stat_details: dict[str, Any] | None = None
        self._goal_suggestion: dict[str, Any] | None = None
        # Bills are CONTEXT here, not the budget - and there are 76 of
        # them. Shown by default they bury the handful of limits you
        # actually set, which is the only part of this page you act on.
        self._show_commitments = False
        self._suggestions: list[dict[str, Any]] = []
        self._dismissed_suggestions: list[dict[str, Any]] = []
        self._show_dismissed = False
        self._suggestion_selection: set[int] = set()

        self._goal_field = FormTextField(
            label="",
            show_label=False,
            hint='e.g. "I wanna cut back on Starbucks"',
        )
        self._goal_result = ft.Container()
        self._stats = ft.Container()

        goal_card = SectionCard(
            title="Set a goal in plain English",
            body=ft.Column(
                [
                    ft.Row(
                        [
                            self._goal_field,
                            PulseButton(
                                on_click_callable=self._submit_goal,
                                text="Set budget",
                                compact=True,
                            ),
                        ],
                        spacing=Theme.Spacing.SM,
                        vertical_alignment=ft.CrossAxisAlignment.END,
                    ),
                    self._goal_result,
                ],
                spacing=Theme.Spacing.SM,
            ),
            body_padding=Theme.Spacing.MD,
        )

        # The goal box is built but NOT mounted. It is a good idea with
        # nothing behind it yet: a full-width empty input at the top of
        # the page, above the numbers, asking to be typed into before
        # there is any budget to steer. The stats strip earns its place
        # (it reads even at zero), so that stays. Re-add ``goal_card``
        # here when the parse-then-accept flow is worth the real estate.
        self._goal_card = goal_card
        # Sub-tabs, one scroll context each. With suggestions ON the
        # limits page, its table scrolled inside a page that also
        # scrolled - two nested scrollbars fighting over the wheel. Each
        # tab now owns exactly one.
        self._subtab_index = 0
        self._goals: list[dict[str, Any]] = []
        self._envelopes: list[dict[str, Any]] = []
        self._outlook: list[dict[str, Any]] = []
        self._outlook_index = 0
        self._budget_tabs = PulseTabs(
            tabs=[
                ft.Tab(text="Limits"),
                ft.Tab(text="Suggested"),
                ft.Tab(text="Goals"),
                ft.Tab(text="Envelopes"),
            ],
            selected_index=0,
            expand=False,
            on_change=self._on_subtab_change,
        )
        self._body = ft.Container(expand=True)
        # The explanatory sentence rides an info icon instead of its own
        # line, and the month pager shares the title's row - together
        # that returns two rows of height to the tab's actual content.
        self._pager_slot = ft.Container()
        self.content = ft.Column(
            [
                ft.Row(
                    [
                        H3Text("Does the month work?"),
                        ft.Icon(
                            ft.Icons.INFO_OUTLINE,
                            size=16,
                            color=Theme.Colors.TEXT_SECONDARY,
                            tooltip=(
                                "Your plan checked against how you actually "
                                "spend, and where that leaves your balance "
                                "in the months ahead"
                            ),
                        ),
                        ft.Container(expand=True),
                        self._pager_slot,
                    ],
                    spacing=Theme.Spacing.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._stats,
                self._budget_tabs,
                self._body,
                self._stat_detail,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    def _on_subtab_change(self, event: ft.ControlEvent) -> None:
        self._subtab_index = int(event.control.selected_index or 0)
        # Paint the cached data instantly, then refetch behind it - the
        # suggestions and commitment totals both react to what the other
        # tabs just did.
        self._render()
        if self.page:
            self.page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state
        from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

        api = get_session_state(self.page).api_client
        if not self._categories:
            cat_data = await api.get("/api/v1/finance/categories/options")
            cat_items = cat_data.get("items", []) if isinstance(cat_data, dict) else []
            self._categories = [
                (str(c["id"]), c["name"])
                for c in cat_items
                if str(c.get("name", "")).lower() not in UNCATEGORIZED_CATEGORY_NAMES
            ]
        # An explicit empty selection ("Remove all") means literally nothing,
        # not "no filter" - AccountFilter.params() is never called in this
        # state (see its own docstring), so the fetch is skipped outright,
        # same as OverviewTab's own charts and UncategorizedPanel do.
        data: dict[str, Any] = (
            {"buckets": [], "stats": {}, "trims": []}
            if self._account_filter.is_empty
            else await api.get(
                "/api/v1/finance/budget/summary", params=self._account_filter.params()
            )
        )
        self._summary = data if isinstance(data, dict) else None
        self._stat_details = None
        goals = await api.get("/api/v1/finance/goals")
        self._goals = goals.get("items", []) if isinstance(goals, dict) else []
        envelopes = await api.get("/api/v1/finance/envelopes")
        self._envelopes = (
            envelopes.get("items", []) if isinstance(envelopes, dict) else []
        )
        outlook = (
            {"items": []}
            if self._account_filter.is_empty
            else await api.get(
                "/api/v1/finance/budget/outlook",
                params={"months": 6, **self._account_filter.params()},
            )
        )
        self._outlook = outlook.get("items", []) if isinstance(outlook, dict) else []
        picks = await api.get("/api/v1/finance/budget/suggestions")
        self._suggestions = picks.get("items", []) if isinstance(picks, dict) else []
        self._dismissed_suggestions = (
            picks.get("dismissed", []) if isinstance(picks, dict) else []
        )
        # A reload rebuilds the table unchecked; stale indices must not
        # survive into the fresh one.
        self._suggestion_selection = set()
        self._render()

    def _render(self) -> None:
        if not self._summary:
            self._body.content = EmptyStatePlaceholder("Could not load the budget.")
            if self.page:
                self.update()
            return
        buckets = {b["name"]: b for b in self._summary.get("buckets", [])}
        self._stats.content = self._stats_strip(self._summary.get("stats", {}))
        self._pager_slot.content = self._month_pager()
        # Your budget first. The commitment sections are collapsed behind
        # one line so the page opens on what you set, not on 76 bills that
        # Bills & Income already owns.
        label = (
            f"Suggested ({len(self._suggestions)})"
            if self._suggestions
            else "Suggested"
        )
        if self._budget_tabs.tabs[1].text != label:
            self._budget_tabs.tabs[1].text = label
            if self._budget_tabs.page:
                self._budget_tabs.update()
        goals_label = f"Goals ({len(self._goals)})" if self._goals else "Goals"
        if self._budget_tabs.tabs[2].text != goals_label:
            self._budget_tabs.tabs[2].text = goals_label
            if self._budget_tabs.page:
                self._budget_tabs.update()
        envelopes_label = (
            f"Envelopes ({len(self._envelopes)})" if self._envelopes else "Envelopes"
        )
        if self._budget_tabs.tabs[3].text != envelopes_label:
            self._budget_tabs.tabs[3].text = envelopes_label
            if self._budget_tabs.page:
                self._budget_tabs.update()
        if self._subtab_index == 3:
            self._body.content = self._envelopes_section()
            if self.page:
                self.update()
            return
        if self._subtab_index == 2:
            self._body.content = self._goals_section()
            if self.page:
                self.update()
            return
        if self._subtab_index == 1:
            # Dismissals keep the section alive even with zero live
            # suggestions - restoring one has to happen somewhere.
            self._body.content = (
                self._suggestions_section()
                if self._suggestions or self._dismissed_suggestions
                else EmptyStatePlaceholder(
                    message="Nothing to suggest - your steady spending is "
                    "covered by bills or budgeted already."
                )
            )
            if self.page:
                self.update()
            return
        children: list[ft.Control] = []
        trims = self._summary.get("trims") or []
        if trims:
            children.append(self._trims_section(trims))
        children.append(self._flexible_section(buckets.get("flexible")))
        children.append(self._commitments_toggle(buckets))
        if self._show_commitments:
            children.append(
                self._commitment_section(
                    "Fixed",
                    "Recurring, same amount every cycle - nothing to decide here",
                    buckets.get("fixed"),
                    "Not budgeted, just shown",
                )
            )
            children.append(
                self._commitment_section(
                    "Non-monthly",
                    "Real, recurring, just not every cycle - set aside a "
                    "monthly slice so it doesn't ambush you",
                    buckets.get("non_monthly"),
                    "Set aside",
                )
            )
        self._body.content = ft.Column(
            children,
            spacing=Theme.Spacing.LG,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        if self.page:
            self.update()

    # -- stats strip -----------------------------------------------------

    def _stats_strip(self, stats: dict[str, Any]) -> ft.Control:
        # Paged past "this month", the four cells recompute for that
        # future month (bills at face value on their real cadence);
        # index 0 keeps the classic monthly-equivalent header.
        if self._outlook_index > 0 and self._outlook_index < len(self._outlook):
            rows = outlook_stats_cells(self._outlook[self._outlook_index])
            # Future months carry no per-row backup yet, so the cells
            # stay plain there.
            cells = [
                self._stat_cell(label, value, caption, color)
                for label, value, caption, color in rows
            ]
        else:
            rows = budget_stats_cells(stats)
            cells = [
                self._stat_cell(
                    label,
                    value,
                    caption,
                    color,
                    on_tap=lambda e, k=label: self._open_stat_detail(k, e),
                )
                for label, value, caption, color in rows
            ]
        return ft.Container(
            content=ft.Row(cells, spacing=Theme.Spacing.LG),
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            bgcolor=ft.Colors.SURFACE,
            padding=ft.padding.symmetric(
                horizontal=Theme.Spacing.LG, vertical=Theme.Spacing.SM
            ),
        )

    def _open_stat_detail(self, key: str, e: ft.ControlEvent) -> None:
        if self.page is not None:
            self.page.run_task(self._open_stat_detail_async, key, e)

    async def _open_stat_detail_async(self, key: str, e: ft.ControlEvent) -> None:
        """Rows for whichever cell was clicked. The verdict and Budgets
        build from the summary already on screen (zero fetch, cannot
        disagree with the strip); Income/Bills/Everything else come from
        one cached /budget/stat-details fetch."""
        stats = (self._summary or {}).get("stats", {})
        if key == "This month":
            self._stat_detail.open_at(
                e, "The month, line by line", equation_rows(stats)
            )
            return
        if key == "Budgets":
            buckets = {b["name"]: b for b in (self._summary or {}).get("buckets", [])}
            rows = [
                {
                    "label": line.get("category_name")
                    or line.get("payee_label")
                    or "Overall",
                    "value": line.get("allocated_amount", 0),
                    "caption": f"{_usd(line.get('spent_amount', 0))} spent",
                }
                for line in buckets.get("flexible", {}).get("lines", [])
            ]
            rows.sort(key=lambda r: -r["value"])
            self._stat_detail.open_at(e, "Limits you've set", rows)
            return
        if self._stat_details is None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            data = await api.get(
                "/api/v1/finance/budget/stat-details",
                params=self._account_filter.params(),
            )
            if not isinstance(data, dict):
                return
            self._stat_details = data
        details = self._stat_details
        if key == "Income":
            self._stat_detail.open_at(e, "Confirmed income", details["income"])
        elif key == "Bills":
            self._stat_detail.open_at(
                e,
                "Bills, monthly equivalent",
                details["bills"],
                footer="Non-monthly bills shown at their monthly share",
            )
        elif key == "Everything else":
            self._stat_detail.open_at(
                e,
                "Everything else",
                details["everything_else"],
                footer=(
                    f"{details.get('window', '')} - observed spending "
                    "no bill or limit covers"
                ),
            )

    def _month_pager(self) -> ft.Control:
        """The months ahead as one row: arrows page the header, the chips
        name each month's verdict - the October that breaks even is
        visible without going looking for it."""
        if not self._outlook:
            return ft.Container()

        def _page(delta: int) -> None:
            self._outlook_index = max(
                0, min(len(self._outlook) - 1, self._outlook_index + delta)
            )
            self._render()

        def _jump(index: int) -> None:
            self._outlook_index = index
            self._render()

        chips: list[ft.Control] = []
        for i, entry in enumerate(self._outlook):
            if i == 0:
                label = f"Now ${round(entry.get('start_balance', 0) / 100):,}"
                color = Theme.Colors.TEXT_SECONDARY
            else:
                label, color = outlook_chip(entry)
            selected = i == self._outlook_index
            chips.append(
                ft.Container(
                    content=SecondaryText(
                        label,
                        size=Theme.Typography.BODY_SMALL,
                        color=color,
                        weight=ft.FontWeight.W_600 if selected else None,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                    border_radius=Theme.Components.BUTTON_RADIUS,
                    border=ft.border.all(
                        1,
                        Theme.Colors.ACCENT if selected else Theme.Colors.BORDER_SUBTLE,
                    ),
                    on_click=lambda _e, i=i: _jump(i),
                    ink=True,
                )
            )
        return ft.Row(
            [
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    icon_size=16,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Previous month",
                    on_click=lambda _e: _page(-1),
                ),
                *chips,
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    icon_size=16,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Next month",
                    on_click=lambda _e: _page(1),
                ),
            ],
            spacing=Theme.Spacing.XS,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        )

    def _stat_cell(
        self,
        label: str,
        value: str,
        caption: str,
        color: str | None = None,
        on_tap: Callable[[ft.ControlEvent], None] | None = None,
    ) -> ft.Control:
        cell = ft.Column(
            [
                SecondaryText(label.upper(), size=Theme.Typography.CAPTION),
                NumericText(
                    value,
                    size=22,
                    weight=Theme.Typography.WEIGHT_BOLD,
                    color=color or Theme.Colors.TEXT_PRIMARY,
                ),
                SecondaryText(caption, size=Theme.Typography.BODY_SMALL),
            ],
            spacing=2,
        )
        if on_tap is None:
            cell.expand = True
            return cell
        # on_tap_down, not on_click: the popup anchors at the tap's own
        # coordinates (the same mechanics every picker trigger uses).
        return ft.Container(
            content=cell,
            expand=True,
            ink=True,
            border_radius=Theme.Components.BUTTON_RADIUS,
            on_tap_down=on_tap,
            on_click=lambda _e: None,
            tooltip="Click for the breakdown",
        )

    def _suggestions_section(self) -> ft.Control:
        """Every line your own spending implies - all of them, not a top
        five. Knowing what your budget is ABOUT means seeing the $20 gym
        alongside the $1,399 groceries; the tail is where the surprises
        live, and hiding it would just be another number nobody chose.

        Rows use the house select-many pattern (checkboxes + bulk verbs),
        so accepting or declining a batch is one gesture - and a declined
        suggestion stays declined across months until restored here.
        """
        total = sum(p.get("suggested_amount", 0) for p in self._suggestions)

        async def _accept_all() -> None:
            await self._accept_suggestions(list(self._suggestions))

        def _checked_picks() -> list[dict[str, Any]]:
            return [
                self._suggestions[i]
                for i in sorted(self._suggestion_selection)
                if i < len(self._suggestions)
            ]

        async def _use_checked() -> None:
            picks = _checked_picks()
            if picks:
                await self._accept_suggestions(picks)

        async def _dismiss_checked() -> None:
            picks = _checked_picks()
            if picks:
                await self._dismiss_suggestions(
                    [p["category_id"] for p in picks if p.get("category_id")]
                )

        use_checked = BulkActionTrigger(
            on_tap=lambda e: e.page.run_task(_use_checked),
            label="Use",
            tooltip="Add every checked suggestion as a budget line",
        )
        dismiss_checked = BulkActionTrigger(
            on_tap=lambda e: e.page.run_task(_dismiss_checked),
            label="Dismiss",
            tooltip=(
                "Hide every checked suggestion. It stays hidden across "
                "months until restored below"
            ),
            variant="stop",
        )

        def _on_selection_change(indices: set[int]) -> None:
            self._suggestion_selection = set(indices)
            use_checked.set_count(len(indices))
            dismiss_checked.set_count(len(indices))

        rows = [
            [
                TableNameText(p.get("category_name") or "Uncategorized"),
                NumericText(_usd(p.get("suggested_amount", 0))),
                SecondaryText(budget_suggestion_caption(p)),
            ]
            for p in self._suggestions
        ]
        children: list[ft.Control] = []
        if self._suggestions:
            children.append(
                DataTable(
                    columns=[
                        DataTableColumn("Category", hideable=False),
                        DataTableColumn("Per month", width=120, alignment="right"),
                        DataTableColumn("Based on", width=220, style="secondary"),
                    ],
                    rows=rows,
                    row_padding=6,
                    item_extent=_DENSE_ROW_HEIGHT,
                    # The table IS the tab: it fills the panel and is
                    # the only thing that scrolls - the nested
                    # table-inside-scrolling-page arrangement fought
                    # over the wheel.
                    expand=True,
                    selectable=True,
                    on_selection_change=_on_selection_change,
                )
            )
        children.extend(self._dismissed_suggestion_rows())
        # No SectionCard: the DataTable already draws its own card, and a
        # card around a card read as a table within a table. One bare
        # action strip above it - summary left, every verb right - at a
        # FIXED height, so the bulk chips appearing on first check don't
        # jump the table down.
        summary = (
            f"{len(self._suggestions)} categories, {_usd(total)}/month · "
            "median of the last 6 complete months, skipping transfers "
            "and anything a bill already covers"
            if self._suggestions
            else "Nothing to suggest. Dismissed suggestions are below."
        )
        strip = ft.Container(
            content=ft.Row(
                [
                    ft.Container(content=SecondaryText(summary), expand=True),
                    dismiss_checked,
                    use_checked,
                    *(
                        [
                            PulseButton(
                                on_click_callable=_accept_all,
                                text=f"Use all {len(self._suggestions)}",
                                compact=True,
                            )
                        ]
                        if self._suggestions
                        else []
                    ),
                ],
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=44,
        )
        return ft.Column(
            [strip, *children],
            spacing=Theme.Spacing.SM,
            expand=True,
        )

    def _dismissed_suggestion_rows(self) -> list[ft.Control]:
        """The "N dismissed · Show" affordance and, when open, the list of
        declined suggestions with a Restore per row - reversibility
        without DB surgery."""
        if not self._dismissed_suggestions:
            return []
        count = len(self._dismissed_suggestions)

        def _toggle(_e: ft.ControlEvent) -> None:
            self._show_dismissed = not self._show_dismissed
            self._render()

        def _restore(category_id: int):
            async def _run() -> None:
                await self._restore_suggestions([category_id])

            return _run

        word = "Hide" if self._show_dismissed else "Show"
        controls: list[ft.Control] = [
            ft.Container(
                content=SecondaryText(
                    f"{count} dismissed  ·  {word}",
                    size=Theme.Typography.BODY_SMALL,
                ),
                on_click=_toggle,
                ink=True,
                border_radius=Theme.Components.BUTTON_RADIUS,
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
            )
        ]
        if self._show_dismissed:
            controls.extend(
                ft.Row(
                    [
                        ft.Container(
                            content=SecondaryText(
                                d.get("category_name") or "Uncategorized"
                            ),
                            expand=True,
                        ),
                        PulseButton(
                            on_click_callable=_restore(d.get("category_id")),
                            text="Restore",
                            variant="muted",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for d in self._dismissed_suggestions
            )
        return controls

    async def _dismiss_suggestions(self, category_ids: list[int]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/suggestions/dismiss",
            json={"category_ids": category_ids},
        )
        if not isinstance(result, dict):
            ErrorSnackBar(
                api.last_error or "Could not dismiss those suggestions."
            ).launch(self.page)
            return
        count = len(category_ids)
        SuccessSnackBar(
            f"Dismissed {count} suggestion{'s' if count != 1 else ''}."
        ).launch(self.page)
        await self._load()

    async def _restore_suggestions(self, category_ids: list[int]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/suggestions/restore",
            json={"category_ids": category_ids},
        )
        if not isinstance(result, dict):
            ErrorSnackBar(
                api.last_error or "Could not restore that suggestion."
            ).launch(self.page)
            return
        await self._load()

    async def _accept_suggestions(self, picks: list[dict[str, Any]]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        saved = 0
        for pick in picks:
            result = await api.post(
                "/api/v1/finance/budget/lines",
                json={
                    "category_id": pick.get("category_id"),
                    "allocated_amount": pick.get("suggested_amount"),
                },
            )
            if isinstance(result, dict):
                saved += 1
        if not saved:
            ErrorSnackBar("Could not add those budget lines.").launch(self.page)
            return
        SuccessSnackBar(
            f"Added {saved} budget line{'s' if saved != 1 else ''}."
        ).launch(self.page)
        await self._load()

    def _commitments_toggle(self, buckets: dict[str, Any]) -> ft.Control:
        """One line standing in for both commitment sections.

        States the total rather than listing it: "what am I already
        committed to" is a number, and the rows behind it are Bills &
        Income's job.
        """
        rows = 0
        total = 0
        for key in ("fixed", "non_monthly"):
            bucket = buckets.get(key) or {}
            lines = bucket.get("lines", []) or []
            rows += len(lines)
            total += sum(line.get("amount", 0) or 0 for line in lines)

        def _toggle(_e: ft.ControlEvent) -> None:
            self._show_commitments = not self._show_commitments
            self._render()

        return ft.Container(
            content=ft.Row(
                [
                    SecondaryText(
                        f"{_usd(total)}/month already committed across "
                        f"{rows:,} bill{'s' if rows != 1 else ''}"
                    ),
                    ft.Container(expand=True),
                    SecondaryText(
                        "Hide bills" if self._show_commitments else "Show bills",
                        color=Theme.Colors.ACCENT,
                    ),
                    ft.Icon(
                        ft.Icons.EXPAND_LESS
                        if self._show_commitments
                        else ft.Icons.EXPAND_MORE,
                        size=18,
                        color=Theme.Colors.ACCENT,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
            ),
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.MD, vertical=10),
            border=ft.border.all(1, ft.Colors.OUTLINE),
            border_radius=Theme.Components.CARD_RADIUS,
            ink=True,
            on_click=_toggle,
        )

    # -- Fixed / Non-monthly: context only, no limit to set or remove ----

    def _commitment_section(
        self,
        title: str,
        subtitle: str,
        bucket: dict[str, Any] | None,
        caption_prefix: str,
    ) -> ft.Control:
        lines = (bucket or {}).get("lines", [])
        total = (bucket or {}).get("total_allocated", 0)
        header = ft.Row(
            [H3Text(title), SecondaryText(subtitle)],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if not lines:
            body: ft.Control = SecondaryText(f"No {title.lower()} bills detected yet.")
        else:
            body = budget_lines_grid([self._commitment_row(line) for line in lines])
        return SectionCard(
            title=header,
            body=body,
            actions=[SecondaryText(f"{caption_prefix} - {_usd(total)}/mo")],
            body_padding=Theme.Spacing.MD,
        )

    def _commitment_row(self, line: dict[str, Any]) -> ft.Control:
        label = line.get("category_name") or "Uncategorized"
        variance = line.get("variance_amount")
        if variance is None:
            status = status_dot(
                "On schedule",
                Theme.Colors.SUCCESS,
                "This period's charge is close to what it typically costs.",
            )
        else:
            sign = "+" if variance > 0 else "-"
            status = status_dot(
                f"{sign}{_usd(abs(variance))} vs last mo.",
                Theme.Colors.WARNING,
                "This period's charge moved from last month's.",
            )
        return ft.Row(
            [
                TableNameText(label),
                ft.Container(expand=True),
                NumericText(f"{_usd(line.get('allocated_amount', 0))} /mo", size=14),
                status,
            ],
            spacing=Theme.Spacing.MD,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    # -- Flexible: the actual budget, chosen limits only ------------------

    def _flexible_section(self, bucket: dict[str, Any] | None) -> ft.Control:
        lines = (bucket or {}).get("lines", [])
        header = ft.Row(
            [
                H3Text("Flexible"),
                SecondaryText("Limits you've set - by category or by payee"),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        if not lines:
            body: ft.Control = SecondaryText(
                "No budget lines set yet - use the goal box above, or "
                "“+ Add a limit” below, for a specific category or payee."
            )
        else:
            body = budget_lines_grid([self._line_row(line) for line in lines])
        return SectionCard(
            title=header,
            body=ft.Column(
                [body, self._add_line_button()],
                spacing=Theme.Spacing.MD,
                tight=True,
            ),
            body_padding=Theme.Spacing.MD,
        )

    def _line_row(self, line: dict[str, Any]) -> ft.Control:
        label = line.get("category_name") or line.get("payee_label") or "Overall"
        progress = compact_budget_row(
            label,
            line.get("allocated_amount", 0),
            line.get("spent_amount", 0),
            line.get("status", "good"),
        )
        # The bar itself opens the editor: a limit you cannot change
        # without deleting and re-adding it is not a dial, and tuning
        # one and watching the month react is the whole loop this tab
        # is for.
        return ft.Row(
            [
                ft.Container(
                    content=progress,
                    expand=True,
                    on_click=lambda _e, row=line: self._open_edit_limit(row),
                    tooltip="Change this limit",
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=14,
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Remove this limit",
                    on_click=lambda e, line_id=line["id"]: e.page.run_task(
                        self._delete_line, line_id
                    ),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _open_edit_limit(self, line: dict[str, Any]) -> None:
        """Change one limit's amount. Everything else about the line -
        its category or payee - is what identifies it, so the dialog
        edits the single number that is a decision."""
        label = line.get("category_name") or line.get("payee_label") or "Overall"
        amount = FormTextField(
            label="Monthly limit ($)",
            value=f"{line.get('allocated_amount', 0) / 100:.2f}",
            width=200,
        )
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            cents = _parse_dollars(amount.value or "")
            if cents <= 0:
                ErrorSnackBar("Give the limit an amount.").launch(self.page)
                return
            await _close()
            await self._save_limit(line, cents)

        spent = line.get("spent_amount", 0)
        dialog = StyledAlertDialog(
            title=f"Limit for {label}",
            body=ft.Column(
                [
                    amount,
                    SecondaryText(
                        f"{_usd(spent)} already spent this month",
                        size=Theme.Typography.BODY_SMALL,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=380,
        )
        self.page.open(dialog)

    async def _save_limit(self, line: dict[str, Any], cents: int) -> None:
        """Upsert the line at a new amount, then reload so the header's
        verdict re-answers on the spot."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/lines",
            json={
                "category_id": line.get("category_id"),
                "payee_key": line.get("payee_key"),
                "payee_label": line.get("payee_label"),
                "allocated_amount": cents,
            },
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not save that limit.").launch(self.page)
            return
        await self._load()

    # -- Envelopes sub-tab ---------------------------------------------

    def _envelopes_section(self) -> ft.Control:
        new_button = PulseButton(
            on_click_callable=lambda: self._open_envelope_editor(None),
            text="New envelope",
            variant="teal",
            compact=True,
        )
        if not self._envelopes:
            return ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                PrimaryText("No envelopes yet."),
                                SecondaryText(
                                    "A running balance inside your real cash - "
                                    "an allowance, a repairs pot. Credit it, "
                                    "spend it down, watch it carry."
                                ),
                                ft.Container(height=Theme.Spacing.SM),
                                new_button,
                            ],
                            spacing=Theme.Spacing.XS,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            tight=True,
                        ),
                        alignment=ft.alignment.center,
                        padding=Theme.Spacing.XL,
                    )
                ],
                expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
            )
        cards = [
            envelope_card(
                env,
                on_spend=(lambda e=env: self._open_envelope_move(e, spend=True)),
                on_credit=(lambda e=env: self._open_envelope_move(e, spend=False)),
                on_edit=(lambda e=env: self._open_envelope_editor(e)),
                on_remove=(lambda e=env: self._confirm_remove_envelope(e)),
            )
            for env in self._envelopes
        ]
        return ft.Column(
            [
                ft.Row([ft.Container(expand=True), new_button]),
                budget_lines_grid(cards),
            ],
            spacing=Theme.Spacing.MD,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def _open_envelope_move(self, envelope: dict[str, Any], *, spend: bool) -> None:
        """Spend from / add to an envelope: one amount, one optional note
        (the note is the history the kid reads later)."""
        verb = "Spend from" if spend else "Add to"
        amount_field = FormTextField(label="Amount ($)", width=320)
        note_field = FormTextField(
            label="Note (optional)", hint="Roblox, mowing the lawn...", width=320
        )
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            cents = dollars_to_cents(amount_field.value)
            if cents is None or cents <= 0:
                amount_field.set_error("Enter a dollar amount.")
                return
            api = get_session_state(self.page).api_client
            action = "spend" if spend else "credit"
            result = await api.post(
                f"/api/v1/finance/envelopes/{envelope['account_id']}/{action}",
                json={
                    "amount": cents,
                    "note": (note_field.value or "").strip() or None,
                },
            )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not save that.").launch(
                    self.page
                )
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title=f"{verb} {envelope.get('name', 'envelope')}",
            body=ft.Column(
                [amount_field, note_field], spacing=Theme.Spacing.SM, tight=True
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Spend" if spend else "Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    def _open_envelope_editor(self, envelope: dict[str, Any] | None) -> None:
        creating = envelope is None
        name_field = FormTextField(
            label="Name", value="" if creating else str(envelope.get("name", ""))
        )
        credit_field = FormTextField(
            label="Credit amount ($, optional)",
            value=(
                ""
                if creating or not envelope.get("monthly_credit")
                else f"{envelope['monthly_credit'] / 100:.2f}"
            ),
        )
        cadence_dd = FormDropdown(
            label="How often?",
            options=[("weekly", "Weekly"), ("monthly", "Monthly")],
            value=(envelope or {}).get("cadence", "monthly"),
        )
        seed_field = FormTextField(
            label="Starting balance ($, optional)",
            hint="Money it begins with",
        )
        auto_switch = ThemedSwitch(
            value=bool((envelope or {}).get("auto_credit")),
            scale=0.8,
        )
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            credit = dollars_to_cents(credit_field.value)
            if creating:
                name = (name_field.value or "").strip()
                if not name:
                    name_field.set_error("Name the envelope.")
                    return
                cadence = cadence_dd.value or "monthly"
                result = await api.post(
                    "/api/v1/finance/envelopes",
                    json={
                        "name": name,
                        "monthly_credit": credit,
                        "cadence": cadence,
                        "starting_balance": dollars_to_cents(seed_field.value) or 0,
                    },
                )
                if isinstance(result, dict) and auto_switch.value:
                    result = await api.patch(
                        f"/api/v1/finance/envelopes/{result['account_id']}",
                        json={
                            "monthly_credit": credit,
                            "auto_credit": True,
                            "cadence": cadence,
                        },
                    )
            else:
                result = await api.patch(
                    f"/api/v1/finance/envelopes/{envelope['account_id']}",
                    json={
                        "monthly_credit": credit,
                        "auto_credit": bool(auto_switch.value),
                        "cadence": cadence_dd.value or "monthly",
                    },
                )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not save that.").launch(
                    self.page
                )
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title="New envelope" if creating else f"Edit {envelope.get('name', '')}",
            body=ft.Column(
                [
                    name_field,
                    *([seed_field] if creating else []),
                    credit_field,
                    cadence_dd,
                    ft.Row(
                        [auto_switch, LabelText("Credit it automatically")],
                        spacing=Theme.Spacing.SM,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Create" if creating else "Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=420,
        )
        self.page.open(dialog)

    def _confirm_remove_envelope(self, envelope: dict[str, Any]) -> None:
        ConfirmDialog(
            page=self.page,
            title="Remove envelope",
            message=(
                f"Remove {envelope.get('name', 'this envelope')}? Its balance "
                "record goes with it."
            ),
            confirm_text="Remove",
            destructive=True,
            on_confirm=lambda: self._remove_envelope(envelope),
        ).show()

    async def _remove_envelope(self, envelope: dict[str, Any]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/envelopes/{envelope['account_id']}")
        await self._load()

    # -- Goals sub-tab -----------------------

    def _goals_section(self) -> ft.Control:
        """Goal cards on the budget-lines grid, or the dreams empty state."""
        new_button = PulseButton(
            on_click_callable=lambda: self._open_goal_editor(None),
            text="New goal",
            variant="teal",
            compact=True,
        )
        if not self._goals:
            return ft.Column(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                PrimaryText("No goals yet."),
                                SecondaryText(
                                    "Name a dream, give it a number, and the "
                                    "month starts saving toward it."
                                ),
                                ft.Container(height=Theme.Spacing.SM),
                                new_button,
                            ],
                            spacing=Theme.Spacing.XS,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            tight=True,
                        ),
                        alignment=ft.alignment.center,
                        padding=Theme.Spacing.XL,
                    )
                ],
                expand=True,
                alignment=ft.MainAxisAlignment.CENTER,
            )
        cards = [
            savings_goal_card(
                goal,
                on_contribute=(lambda g=goal: self._open_goal_contribute(g)),
                on_toggle_pause=(lambda g=goal: self._toggle_goal_pause(g)),
                on_edit=(lambda g=goal: self._open_goal_editor(g)),
                on_remove=(lambda g=goal: self._confirm_remove_goal(g)),
            )
            for goal in self._goals
        ]
        return ft.Column(
            [
                ft.Row([ft.Container(expand=True), new_button]),
                budget_lines_grid(cards),
            ],
            spacing=Theme.Spacing.MD,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    async def _toggle_goal_pause(self, goal: dict[str, Any]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        status = "active" if goal.get("status") == "paused" else "paused"
        result = await api.patch(
            f"/api/v1/finance/goals/{goal['account_id']}", json={"status": status}
        )
        if not isinstance(result, dict):
            ErrorSnackBar(api.last_error or "Could not update the goal.").launch(
                self.page
            )
            return
        await self._load()

    def _confirm_remove_goal(self, goal: dict[str, Any]) -> None:
        linked = goal.get("funding") == "linked"
        ConfirmDialog(
            page=self.page,
            title="Remove goal",
            message=(
                f"Stop tracking {goal.get('name', 'this goal')} as a goal? "
                + (
                    "The account itself stays, untouched."
                    if linked
                    else "Its saved-so-far record goes with it."
                )
            ),
            confirm_text="Remove",
            destructive=True,
            on_confirm=lambda: self._remove_goal(goal),
        ).show()

    async def _remove_goal(self, goal: dict[str, Any]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/goals/{goal['account_id']}")
        await self._load()

    def _open_goal_contribute(self, goal: dict[str, Any]) -> None:
        """add money to a virtual goal; linked goals point at
        transfers (their contributions book themselves)."""
        if goal.get("funding") == "linked":
            ErrorSnackBar(
                "Linked goals count their own transfers - move money to "
                f"{goal.get('name', 'the account')} and it books itself."
            ).launch(self.page)
            return
        amount_field = FormTextField(label="Amount ($)", width=320)
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            cents = dollars_to_cents(amount_field.value)
            if cents is None or cents <= 0:
                amount_field.set_error("Enter a dollar amount.")
                return
            api = get_session_state(self.page).api_client
            result = await api.post(
                f"/api/v1/finance/goals/{goal['account_id']}/contribute",
                json={"amount": cents},
            )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not add that.").launch(self.page)
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title=f"Add to {goal.get('name', 'goal')}",
            body=ft.Column([amount_field], tight=True),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    def _open_goal_editor(self, goal: dict[str, Any] | None) -> None:
        """create (virtual by default, or link an existing account)
        or edit targets. All existing form controls."""
        creating = goal is None
        name_field = FormTextField(
            label="Name", value="" if creating else str(goal.get("name", ""))
        )
        target_field = FormTextField(
            label="Target ($)",
            value="" if creating else f"{goal['target_amount'] / 100:.2f}",
        )
        date_field = FormDateField(
            label="Target date (optional)",
            value=(goal or {}).get("target_date") or "",
        )
        monthly_field = FormTextField(
            label="Monthly amount ($, optional)",
            value=(
                ""
                if creating or not goal.get("monthly_contribution")
                else f"{goal['monthly_contribution'] / 100:.2f}"
            ),
        )
        income_total = (self._summary or {}).get("stats", {}).get("income_total", 0)
        preview = SecondaryText("", size=Theme.Typography.BODY_SMALL)

        def _percent_typed(event: ft.ControlEvent) -> None:
            preview.value = contribution_preview(
                "percent_income",
                getattr(event.control, "value", "") or "",
                income_total=income_total,
            )
            if preview.page is not None:
                preview.update()

        percent_field = FormTextField(
            label="Percent of income (%)",
            value=(
                ""
                if creating or not goal.get("contribution_pct_bps")
                else f"{goal['contribution_pct_bps'] / 100:g}"
            ),
            on_change=_percent_typed,
        )
        monthly_host = ft.Container(content=monthly_field)
        percent_host = ft.Container(content=percent_field, visible=False)
        current_kind = (goal or {}).get("contribution_kind", "fixed")

        def _paint_rule(kind: str) -> None:
            monthly_host.visible = kind == "fixed"
            percent_host.visible = kind == "percent_income"
            preview.value = contribution_preview(
                kind, percent_field.value, income_total=income_total
            )
            for control in (monthly_host, percent_host, preview):
                if control.page is not None:
                    control.update()

        def _rule_changed(event: ft.ControlEvent) -> None:
            _paint_rule(event.control.value or "fixed")

        rule_dd = FormDropdown(
            label="Contribute how?",
            options=[
                ("fixed", "Fixed amount"),
                ("percent_income", "% of income"),
                ("surplus", "Whatever's left each month"),
            ],
            value=current_kind,
            on_change=_rule_changed,
        )
        monthly_host.visible = current_kind == "fixed"
        percent_host.visible = current_kind == "percent_income"
        preview.value = contribution_preview(
            current_kind, percent_field.value, income_total=income_total
        )
        # Label as its own control beside the switch, not ft.Switch's
        # built-in label: the built-in renders Material's small caption
        # next to a 0.5-scaled knob and the whole row reads miniature.
        # LabelText is the same widget the field labels above it use, and
        # 0.8 is the scale the voice tab's dialog switches settled on.
        auto_switch = ThemedSwitch(
            value=bool((goal or {}).get("auto_contribute")),
            scale=0.8,
        )
        # Only virtual goals auto-book - a linked goal's real transfers
        # are its bookings. Hidden, not disabled: an inert switch invites
        # a support question the row can't answer.
        auto_host = ft.Container(
            content=ft.Row(
                [auto_switch, LabelText("Book it automatically on the 1st")],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=creating or (goal or {}).get("funding") != "linked",
        )
        # Funding picker only at creation - a goal doesn't change species.
        link_dd: FormDropdown | None = None
        link_host = ft.Container(visible=False)
        name_host = ft.Container(content=name_field)
        dialog: StyledAlertDialog | None = None

        async def _close() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _save() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            target = dollars_to_cents(target_field.value)
            if target is None or target <= 0:
                target_field.set_error("Every dream needs a number.")
                return
            kind = rule_dd.value or "fixed"
            monthly = dollars_to_cents(monthly_field.value)
            payload: dict[str, Any] = {
                "target_amount": target,
                "target_date": date_field.value or None,
                "monthly_contribution": monthly if kind == "fixed" else None,
                "contribution_kind": kind,
            }
            if kind == "percent_income":
                raw_pct = (percent_field.value or "").replace("%", "").strip()
                try:
                    bps = round(float(raw_pct) * 100)
                except ValueError:
                    bps = 0
                if not 0 < bps <= 10_000:
                    percent_field.set_error("A percent between 0 and 100.")
                    return
                payload["contribution_pct_bps"] = bps
            payload["auto_contribute"] = bool(auto_switch.value)
            api = get_session_state(self.page).api_client
            if creating:
                choice = link_dd.value if link_dd is not None else "virtual"
                if choice == "virtual":
                    name = (name_field.value or "").strip()
                    if not name:
                        name_field.set_error("Name the goal.")
                        return
                    payload["name"] = name
                else:
                    payload["account_id"] = int(choice)
                    payload["auto_contribute"] = False
                result = await api.post("/api/v1/finance/goals", json=payload)
            else:
                result = await api.patch(
                    f"/api/v1/finance/goals/{goal['account_id']}", json=payload
                )
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Could not save the goal.").launch(
                    self.page
                )
                return
            await _close()
            await self._load()

        dialog = StyledAlertDialog(
            title="New goal" if creating else f"Edit {goal.get('name', 'goal')}",
            body=ft.Column(
                [
                    link_host,
                    name_host,
                    target_field,
                    date_field,
                    rule_dd,
                    monthly_host,
                    percent_host,
                    preview,
                    auto_host,
                ],
                spacing=Theme.Spacing.SM,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                PulseButton(
                    on_click_callable=_close,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Create" if creating else "Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=460,
        )

        def _install(dd: FormDropdown) -> None:
            nonlocal link_dd
            link_dd = dd

        self.page.open(dialog)
        if creating and self.page:
            self.page.run_task(
                self._offer_linkable_accounts,
                link_host,
                name_host,
                auto_host,
                _install,
            )

    async def _offer_linkable_accounts(
        self,
        link_host: ft.Container,
        name_host: ft.Container,
        auto_host: ft.Container,
        install: Callable[[FormDropdown], None],
    ) -> None:
        """Fetch accounts and, when any are linkable, add the funding
        picker to the open create dialog. Fetched on open, not at tab
        build - the list must be current, and most opens never link."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/finance/accounts")
        accounts = data.get("items", []) if isinstance(data, dict) else []
        options = linkable_account_options(accounts)
        if not options:
            return

        def _mode_changed(event: ft.ControlEvent) -> None:
            virtual = event.control.value == "virtual"
            name_host.visible = virtual
            auto_host.visible = virtual
            for control in (name_host, auto_host):
                if control.page is not None:
                    control.update()

        dd = FormDropdown(
            label="Fund it how?",
            options=[("virtual", "Save toward it here (virtual)")]
            + [(key, f"Track {label}") for key, label in options],
            value="virtual",
            on_change=_mode_changed,
        )
        install(dd)
        link_host.content = dd
        link_host.visible = True
        if link_host.page is not None:
            link_host.update()

    def _trims_section(self, trims: list[dict[str, Any]]) -> ft.Control:
        """The month is short - here is what closes it.

        Deterministic, computed server-side (``plan_budget_trims``): cuts
        distribute proportionally to each line's slack above what it has
        already spent, so no suggestion asks for money that is gone.
        Each row applies on its own; nothing is written until one is.
        """

        def row(trim: dict[str, Any]) -> ft.Row:
            title, delta, sub = close_gap_row_copy(trim)
            is_pause = trim.get("kind") == "pause_goal"
            return ft.Row(
                [
                    ft.Container(
                        content=ft.Column(
                            [
                                TableNameText(title),
                                SecondaryText(sub, size=Theme.Typography.BODY_SMALL),
                            ],
                            spacing=0,
                            tight=True,
                        ),
                        expand=True,
                    ),
                    NumericText(
                        delta,
                        size=Theme.Typography.BODY_SMALL,
                        # Recovered money reads calm, taken money warns.
                        color=(
                            Theme.Colors.SUCCESS if is_pause else Theme.Colors.WARNING
                        ),
                    ),
                    PulseButton(
                        on_click_callable=(lambda t=trim: self._apply_trim(t)),
                        text="Apply",
                        variant="muted",
                        compact=True,
                    ),
                ],
                spacing=Theme.Spacing.MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )

        # Server order is already goals-first (plan_budget_trims tier 1).
        rows = [row(trim) for trim in trims]
        total = sum(t.get("cut") or t.get("recovered", 0) for t in trims)
        return SectionCard(
            title=ft.Row(
                [
                    H3Text("Close the gap"),
                    SecondaryText(
                        f"Free up {_usd(total)} across {len(trims)} "
                        f"row{'s' if len(trims) != 1 else ''} to break even"
                    ),
                ],
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            body=budget_lines_grid(rows),
            body_padding=Theme.Spacing.MD,
        )

    async def _apply_trim(self, trim: dict[str, Any]) -> None:
        if trim.get("kind") == "pause_goal":
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            api = get_session_state(self.page).api_client
            await api.patch(
                f"/api/v1/finance/goals/{trim['account_id']}",
                json={"status": "paused"},
            )
            await self._load()
            return
        await self._save_limit(trim, trim["suggested_amount"])

    async def _delete_line(self, line_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/budget/lines/{line_id}")
        await self._load()

    # -- goal box ------------------------------------------------------

    async def _submit_goal(self) -> None:
        text = self._goal_field.value.strip()
        if not text:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post("/api/v1/finance/budget/goal", json={"text": text})
        if not isinstance(result, dict) or not result.get("matched"):
            message = (
                result.get("message")
                if isinstance(result, dict)
                else api.last_error or "Could not parse that."
            )
            ErrorSnackBar(message or "No match found.").launch(self.page)
            self._goal_suggestion = None
            self._goal_result.content = None
            if self.page:
                self.update()
            return
        self._goal_suggestion = result
        self._goal_result.content = self._suggestion_row(result)
        if self.page:
            self.update()

    def _suggestion_row(self, suggestion: dict[str, Any]) -> ft.Control:
        amount = suggestion.get("suggested_limit") or 0
        return ft.Row(
            [
                Tag("PARSED", color=Theme.Colors.ACCENT),
                ft.Container(
                    content=TableCellText(suggestion.get("message") or ""),
                    expand=True,
                ),
                PulseButton(
                    on_click_callable=self._dismiss_goal,
                    text="Adjust",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=self._accept_goal,
                    text=f"Confirm ${amount / 100:,.0f}",
                    variant="teal",
                    compact=True,
                ),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def _accept_goal(self) -> None:
        suggestion = self._goal_suggestion
        if suggestion is None:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/budget/lines",
            json={
                "category_id": suggestion.get("category_id"),
                "payee_key": suggestion.get("payee_key"),
                "payee_label": suggestion.get("payee_label"),
                "allocated_amount": suggestion.get("suggested_limit") or 0,
            },
        )
        if result is None:
            ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
            return
        SuccessSnackBar("Budget line set.").launch(self.page)
        self._goal_suggestion = None
        self._goal_result.content = None
        self._goal_field.value = ""
        await self._load()

    async def _dismiss_goal(self) -> None:
        self._goal_suggestion = None
        self._goal_result.content = None
        if self.page:
            self.update()

    # -- manual add ------------------------------------------------------

    def _add_line_button(self) -> ft.Control:
        return ft.Row(
            [
                PulseButton(
                    on_click_callable=self._open_add_line,
                    text="+ Add a limit",
                    variant="muted",
                    compact=True,
                )
            ]
        )

    async def _open_add_line(self) -> None:
        form: dict[str, str] = {"amount": ""}
        category_dd = FormDropdown(
            label="Category",
            options=self._categories,
            value=self._categories[0][0] if self._categories else None,
            width=360,
        )
        amount = FormTextField(
            label="Monthly limit ($)",
            on_change=lambda e: form.__setitem__(
                "amount", getattr(e.control, "value", "") or ""
            ),
            width=360,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _add() -> None:
            cents = _parse_dollars(form["amount"])
            if cents <= 0:
                ErrorSnackBar("Limit must be more than $0.").launch(self.page)
                return
            if not category_dd.value:
                ErrorSnackBar("Pick a category.").launch(self.page)
                return
            dialog.open = False
            self.page.update()

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.post(
                "/api/v1/finance/budget/lines",
                json={
                    "category_id": int(category_dd.value),
                    "allocated_amount": cents,
                },
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
                return
            SuccessSnackBar("Budget line set.").launch(self.page)
            await self._load()

        dialog = StyledAlertDialog(
            title="Add a category limit",
            body=ft.Column([category_dd, amount], spacing=Theme.Spacing.MD, tight=True),
            actions=[
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_add,
                    text="Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)


class _LazyTabContent(ft.Container):
    """Builds a tab's content on first visit instead of at modal open.

    Seven tabs each fetching their world the moment the modal opens is why
    the modal felt heavy: every open paid for every tab. Content is built
    (and its ``did_mount`` loads fire) only when the tab is first selected.
    """

    def __init__(self, factory: Callable[[], ft.Control]) -> None:
        super().__init__(expand=True)
        self._factory = factory
        self._built = False

    def ensure_built(self) -> bool:
        """Build on first visit. Returns True when the tab was ALREADY
        built - a revisit, where a panel's data may have gone stale."""
        if self._built:
            return True
        self._built = True
        self.content = self._factory()
        if self.page is not None:
            self.update()
        return False


class FinanceDetailDialog(BaseDetailPopup):
    """Finance detail modal — a tabbed workspace.

    Six tabs you would open on a normal day (Overview, Accounts,
    Bills & Income, Projected, Budget, Review) plus a gear holding the
    setup surfaces. Review is itself tabbed (Uncategorized / Transfers /
    Attention - Attention merges the analyst note with the rule findings
    it was written from); Connections and Categories live behind the gear.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        from .finance_recurring_tab import ProjectionPanel, RecurringTab
        from .finance_settings_tab import SettingsTab

        # The analyst only exists in builds that selected the AI service, and
        # the service reports that in its status metadata. Without it the
        # Attention sub-tab (under Review) is the findings alone rather than
        # an empty slot.
        analyst_enabled = bool((component_data.metadata or {}).get("analyst_enabled"))

        # One account-selection shared across every tab that consumes it
        # (Overview, Review's embedded UncategorizedPanel) - dialog-owned
        # so a narrower view follows the user from tab to tab. The FILTER
        # BUTTON itself is dialog-owned too, one instance shown once above
        # the tab strip rather than one per consuming tab: two separate
        # buttons sharing one AccountFilter (the original design) meant
        # two separate menus to keep visually in sync, and the second one
        # only got redrawn on ITS OWN first load, so a change made via one
        # button left the other's dots/trigger label stale until its next
        # unrelated reload (confirmed live, on the Review tab). One button
        # can't drift from itself.
        #
        # ADOPTED from the process-level view-state store, not constructed:
        # this dialog is cached on ``page.data`` and dies with the Flet
        # session (a page reload; every hot-reload in dev), and a filter
        # that silently resets to "All accounts" makes the same screen
        # tell a different story than it told a minute ago - confirmed
        # live, on the projection's sign. The store hands every recreation
        # the SAME AccountFilter instance, so mutations carry forward.
        from app.components.frontend.state.finance_view_state import (
            SOLO_OWNER_KEY,
            finance_view_state,
        )
        from app.components.frontend.state.session_state import get_session_state

        user = getattr(get_session_state(page), "current_user", None)
        owner_key = (
            str(user["id"])
            if isinstance(user, dict) and user.get("id") is not None
            else SOLO_OWNER_KEY
        )
        self._account_filter = finance_view_state(owner_key=owner_key).account_filter
        self._account_items: list[dict] = []
        # Called after every filter change, in registration order, so a
        # tab reloads even while it's not the one currently on screen -
        # otherwise switching back to an already-built (lazy-loaded) tab
        # after changing the filter elsewhere would show stale data until
        # some OTHER trigger happened to reload it.
        self._filter_listeners: list[Callable[[], None]] = []
        self._account_filter_button = AccountFilterButton(
            on_change=self._on_account_filter_change,
            account_filter=self._account_filter,
        )

        # Ordered by how often you look at it, summary first; Review sits
        # after Projected, last of the reading tabs, since it's a queue you
        # work through rather than numbers you read - and now hosts
        # Attention as one of its own sub-tabs (Uncategorized / Transfers /
        # Attention) rather than that living as a sixth top-level tab of
        # its own. Connections and Categories are setup, not reading, so
        # they sit behind the gear at the end. The gear is a Tab with an
        # icon and no text, so it costs a few pixels and nothing you use
        # daily gets nested.
        factories: list[tuple[str, Callable[[], ft.Control], str | None]] = [
            (
                "Overview",
                lambda: OverviewTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Accounts",
                lambda: AccountsTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Bills & Income",
                lambda: RecurringTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Projected",
                lambda: ProjectionPanel(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Budget",
                lambda: BudgetPanel(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Review",
                lambda: ReviewTab(
                    page,
                    analyst_enabled=analyst_enabled,
                    account_filter=self._account_filter,
                    register_filter_listener=self.register_filter_listener,
                ),
                None,
            ),
            (
                "",
                lambda: SettingsTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                ft.Icons.SETTINGS_OUTLINED,
            ),
        ]

        self._lazy_contents = [_LazyTabContent(factory) for _, factory, _ in factories]
        tab_list = [
            ft.Tab(text=name or None, icon=icon, content=content)
            for (name, _, icon), content in zip(
                factories, self._lazy_contents, strict=False
            )
        ]

        def _on_tab_change(event: ft.ControlEvent) -> None:
            index = int(event.control.selected_index or 0)
            if 0 <= index < len(self._lazy_contents):
                lazy = self._lazy_contents[index]
                if lazy.ensure_built():
                    # A revisit. Panels fetch once in did_mount, so a
                    # change made on ANOTHER tab (confirming a bill that
                    # should suppress a budget suggestion) went stale
                    # silently until the modal was reopened. A panel that
                    # opts in refetches; its data is a cheap read, so no
                    # visible "refresh" chrome is needed.
                    refresh = getattr(lazy.content, "refresh_on_revisit", None)
                    if callable(refresh):
                        refresh()

        tabs = PulseTabs(
            selected_index=0,
            tabs=tab_list,
            expand=True,
            on_change=_on_tab_change,
        )
        # The initial tab is visible immediately; build it now.
        self._lazy_contents[0].ensure_built()
        # Pinned above the tab strip, right-aligned - visible (and the
        # SAME control) no matter which tab is selected, rather than
        # living inside whichever tab happened to build it first.
        filter_row = ft.Row(
            [ft.Container(expand=True), self._account_filter_button],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_finance"),
            subtitle_text="Accounts, transactions, and investments",
            sections=[filter_row, tabs],
            scrollable=False,
            width=1600,
            height=900,
            status_detail=get_status_detail(component_data),
        )

    def did_mount(self) -> None:
        if self.page:
            self.page.run_task(self._load_accounts)

    def register_filter_listener(self, callback: Callable[[], None]) -> None:
        """A consuming tab's own reload trigger, called after every
        filter change - see ``_filter_listeners`` for why this covers
        tabs that aren't currently on screen too."""
        self._filter_listeners.append(callback)

    async def _load_accounts(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get("/api/v1/finance/accounts", params={"page_size": 200})
        self._account_items = data.get("items", []) if isinstance(data, dict) else []
        self._account_filter_button.set_accounts(self._account_items)

    def _on_account_filter_change(self) -> None:
        # Redraws THIS button's own dots/trigger label - there's only one
        # now, but it still doesn't repaint itself just because .selected
        # changed underneath it.
        self._account_filter_button.set_accounts(self._account_items)
        for listener in self._filter_listeners:
            listener()
