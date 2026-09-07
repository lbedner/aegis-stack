"""Tuning constants for the finance workspace.

Every value here is a judgement someone made against a real ledger, and
the comment beside it is the evidence. They live together so a change to
one is a change made next to its reason.
"""

from app.components.frontend.controls import DataTableColumn
from app.services.finance.constants import (
    CADENCES,
    ONE_TIME_FREQUENCY,
    ONE_TIME_LABEL,
)
from app.services.system.models import ComponentStatusType

_SIDEBAR_WIDTH = 320
# Named rows in the import review's detail sections before the tail folds
# into a count. A Quicken tree can carry hundreds of new categories, and a
# dialog that scrolls for a page stops being read at all.
_PREVIEW_DETAIL_CAP = 10
_PREVIEW_DETAIL_HEIGHT = 440
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


# account_type -> display group, in sidebar order (Quicken-style buckets).
_ACCOUNT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Banking", ("checking", "savings", "cash")),
    ("Credit Cards", ("credit_card",)),
    ("Investments", ("investment", "brokerage", "crypto")),
    ("Property", ("property", "vehicle")),
    ("Loans & Debt", ("loan", "other_liability")),
    ("Other", ("other_asset",)),
)

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

# Passed as RecordDetailDialog's collapsed_sections at every transaction
# detail call site - one constant so the section name can't drift out of
# sync between transaction_detail_sections's own list and each caller.
_TRANSACTION_COLLAPSED_SECTIONS = frozenset({"Import & reconciliation"})

# One register fetch. Load more widens by another page of this.
_REGISTER_PAGE_SIZE = 100

# The sentinel option key for "create a new account" in the investment
# import's target picker. A string because FormDropdown keys are strings;
# real accounts ride as str(id).
_NEW_ACCOUNT_KEY = "new"

# Matches the Category DataTableColumn's own width below - see
# UncategorizedPanel's _CATEGORY_COLUMN_WIDTH for why the category cell
# needs an explicit width at all (category_trigger_cell relies on it).
_TXN_CATEGORY_COLUMN_WIDTH = 200

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
