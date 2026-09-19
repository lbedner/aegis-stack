"""Opening what a number on the overview stands for."""

from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.table import TableCellText, TableNameText
from app.components.frontend.dashboard.modals.base_popup import OverlayStyledDialog

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
    _amount_cell,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    _transaction_expanded_content,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_panel import (
    UncategorizedPanel,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    date_cell,
)


class OverviewDrilldownMixin:
    """A pie slice, a category, the uncategorized queue.

    Each opens a dialog over the overview; what they read is set up
    by ``OverviewTab.__init__`` and declared here.
    """

    if TYPE_CHECKING:
        page: ft.Page | None
        _account_filter: Any
        _body: ft.Column
        _days: int
        _pending_changes: Any
        _pie_slice_categories: list[str]
        _stats: Any
        _uncategorized_dialog: Any
        _uncategorized_panel: Any

        async def _load(self, *args: Any, **kwargs: Any) -> Any: ...

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
