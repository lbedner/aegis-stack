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
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.controls import (
    DataTableColumn,
)
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
    _DECLARE_GROUP_CHROME,
    _DENSE_ROW_HEIGHT,
    _DIALOG_FIXED_CHROME,
    _GROUP_TABLE_CHROME,
    _GROUP_TABLE_MIN_HEIGHT,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    post_tag,
)


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


class TagApplyMixin:
    """The tag verb every curation surface shares.

    ``TagPickerButton``'s ``on_pick`` and ``on_create`` both land here -
    creating a tag and applying one are the same server verb. Identical in
    all three panels before extraction; the host provides ``page`` (any
    ``ft.Control``) and an async ``_load``.
    """

    if TYPE_CHECKING:
        page: ft.Page | None

        async def _load(self, *args: Any, **kwargs: Any) -> Any: ...

    def _apply_tag(self, transaction_ids: list[int], name: str) -> None:
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_tag_async, transaction_ids, name.strip())

    async def _apply_tag_async(self, transaction_ids: list[int], name: str) -> None:
        if await post_tag(self.page, transaction_ids, name):
            await self._load()


def range_start(range_days: int) -> "date | None":
    """The register/curation date floor: today minus the chip's window,
    or ``None`` for the "All" sentinel (>= 9000, per insights)."""
    if range_days >= 9000:
        return None
    return date.today() - timedelta(days=range_days)
