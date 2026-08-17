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

import flet as ft

from app.components.frontend.controls.record_detail import (
    build_field_blocks,
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
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _qty,
    _trade_type_label,
    _usd,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date


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
