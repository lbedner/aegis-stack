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
from typing import Any

import flet as ft

from app.components.frontend.controls import (
    ActionDropdown,
    MenuAction,
    NumericText,
    PrimaryText,
    SecondaryText,
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
    _INVESTMENT_TYPES,
    _NEW_ACCOUNT_KEY,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.finance_modal.import_preview import (
    _import_count_controls,
    _import_footnote,
    _preview_dot,
    _preview_metric,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date


def nothing_to_import(preview: dict[str, Any]) -> bool:
    """True when the review has nothing to offer an Import button.

    Two shapes of the same dead end: the byte-identical re-upload, and a
    fresh export whose every row is already stored (yesterday's import,
    or a sync, got there first). Parse errors disqualify - a file that
    partly failed deserves the full review, not a shrug.
    """
    if preview.get("identical_batch_id") is not None:
        return True
    return (
        preview.get("rows_inserted", 0) == 0
        and preview.get("rows_updated", 0) == 0
        and preview.get("rows_error", 0) == 0
    )


def import_up_to_date_body(preview: dict[str, Any], file_name: str) -> ft.Column:
    """The body for a file with nothing to import, byte-identical or not.

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
    identical = preview.get("identical_batch_id") is not None
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
                    (
                        _preview_dot(
                            "identical file",
                            False,
                            Theme.Colors.TEXT_SECONDARY,
                            "Matched by content hash, so a rename would not fool it.",
                        )
                        if identical
                        else _preview_dot(
                            "up to date",
                            False,
                            Theme.Colors.TEXT_SECONDARY,
                            "Every row this file carries is already stored - an "
                            "earlier import or sync brought them in.",
                        )
                    ),
                ],
                spacing=Theme.Spacing.MD,
                wrap=True,
            ),
            # Short: the dots above already carry the outcome, so this
            # only has to say WHY, once.
            _import_footnote(
                "Nothing has been written. You already imported this exact file."
                if identical
                else "Nothing has been written. Your ledger already has "
                "everything this file carries."
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


def account_target_options(
    accounts: list[dict[str, Any]],
    selected_id: int | None,
    *,
    types: frozenset[str] | None = None,
    allow_new: bool = False,
) -> tuple[list[tuple[str, str]], str]:
    """(options, default key) for an import's "into account" picker.

    ``types`` narrows the offer (a trade ledger never belongs in checking);
    ``allow_new`` adds a create-new entry so the picker is never a dead end.
    The default follows the sidebar selection when it is on offer, else
    create-new when allowed, else the first account.
    """
    options = [
        (str(a["id"]), str(a.get("name", "")))
        for a in accounts
        if a.get("id") is not None
        and (types is None or a.get("account_type") in types)
    ]
    if allow_new:
        options.append((_NEW_ACCOUNT_KEY, "Create a new account..."))
    default = _NEW_ACCOUNT_KEY if allow_new else (options[0][0] if options else "")
    if selected_id is not None and any(k == str(selected_id) for k, _ in options):
        default = str(selected_id)
    return options, default


def investment_target_options(
    accounts: list[dict[str, Any]], selected_id: int | None
) -> tuple[list[tuple[str, str]], str]:
    """The investment import's picker: investment-typed accounts plus
    create-new, defaulting to the sidebar selection only when that is
    itself an investment account."""
    return account_target_options(
        accounts, selected_id, types=_INVESTMENT_TYPES, allow_new=True
    )


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
