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

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    SecondaryText,
    Tag,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.record_detail import (
    HeroSpec,
    build_field_blocks,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.controls.table import TableCellText, TableNameText

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
    _DENSE_ROW_HEIGHT,
    _TRANSACTION_COLLAPSED_SECTIONS,
    _TXN_CATEGORY_COLUMN_WIDTH,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
    _category_leaf,
    _usd,
    _yn,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    date_cell,
    ledger_amount_color,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date

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


def split_summary_label(splits: list[dict]) -> str:
    """The category cell's text for a split parent: the first line's leaf
    category plus how many more - "Split · Groceries +1". The parent's own
    category is deliberately absent; once split, it no longer reports."""
    first = _category_leaf(splits[0].get("category") or "") or "Uncategorized"
    more = len(splits) - 1
    return f"Split · {first} +{more}" if more else f"Split · {first}"


def split_tooltip(splits: list[dict]) -> str:
    """Hover detail for a split parent's category cell: every line as
    ``category  amount``, memo appended when present."""
    lines = []
    for split in splits:
        line = f"{split.get('category') or 'Uncategorized'}  {_usd(split.get('amount', 0))}"
        if split.get("memo"):
            line += f" · {split['memo']}"
        lines.append(line)
    return "\n".join(lines)


def _split_lines_block(
    txn: dict,
    on_edit_split: Callable[[dict], None] | None,
    on_unsplit: Callable[[dict], None] | None,
) -> list[ft.Control]:
    """The row-expand's split section: the lines themselves plus the
    edit/remove (or way-in) actions. Empty when no callbacks are given -
    surfaces outside the register render exactly as before."""
    if on_edit_split is None and on_unsplit is None:
        return []
    blocks: list[ft.Control] = []
    splits = txn.get("splits") or []
    for split in splits:
        row = [
            SecondaryText(
                split.get("category") or "Uncategorized",
                size=Theme.Typography.BODY_SMALL,
            ),
            ft.Text(
                _usd(split.get("amount", 0)),
                size=Theme.Typography.BODY_SMALL,
                color=Theme.Colors.TEXT_PRIMARY,
            ),
        ]
        if split.get("memo"):
            row.append(
                SecondaryText(str(split["memo"]), size=Theme.Typography.CAPTION)
            )
        blocks.append(
            ft.Row(
                row,
                spacing=Theme.Spacing.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
    def _action(label: str, callback: Callable[[dict], None]) -> ft.Control:
        async def _fire(target: dict = txn) -> None:
            callback(target)

        return PulseButton(
            on_click_callable=_fire, text=label, variant="muted", compact=True
        )

    actions: list[ft.Control] = []
    if txn.get("is_split"):
        if on_edit_split is not None:
            actions.append(_action("Edit split", on_edit_split))
        if on_unsplit is not None:
            actions.append(_action("Remove split", on_unsplit))
    elif on_edit_split is not None and txn.get("id") is not None:
        actions.append(_action("Split into categories…", on_edit_split))
    if actions:
        blocks.append(ft.Row(actions, spacing=Theme.Spacing.SM))
    return blocks


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
    data = await api.get("/api/v1/finance/tags", cache_ttl=30)
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
    txn: dict,
    on_remove_tag: Callable[[dict, dict], None] | None = None,
    on_edit_split: Callable[[dict], None] | None = None,
    on_unsplit: Callable[[dict], None] | None = None,
) -> ft.Control:
    """A transaction's inline row-expand content: the supplementary field
    sections only, no hero - unlike a modal (which starts from nothing),
    this renders directly under a row whose own cells already show payee/
    date/category/amount, so repeating those here would just be heavier
    for no new information.

    ``on_remove_tag(txn, tag)``, when given and the row wears tags, adds a
    Tags block whose chips each carry the remove ``x`` - taking a flag OFF
    happens here, next to everything else about the row.

    ``on_edit_split``/``on_unsplit`` add the split section: the row's
    lines plus edit/remove actions (or the way in, on an unsplit row)."""
    blocks = _split_lines_block(txn, on_edit_split, on_unsplit)
    blocks += build_field_blocks(
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
