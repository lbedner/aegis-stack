"""Filling the register: rows, holdings, and the counts above them."""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
)
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.table import (
    TableCellText,
    TableNameText,
)
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _DENSE_ROW_HEIGHT,
    _REGISTER_PAGE_SIZE,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    range_start,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _account_display_balance,
    _amount_cell,
    _investment_section,
    _qty,
    _trade_type_label,
    _usd,
)
from app.components.frontend.dashboard.modals.finance_modal.trades_view import (
    _trade_expanded_content,
    trades_within_page,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.rows import (
    RegisterRowBuilder,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    register_columns,
    register_count_label,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    EmptyStatePlaceholder,
    date_cell,
)
from app.components.frontend.theme import AegisTheme as Theme


class RegisterLoadMixin(TransactionsPanelState):
    """Every read the register makes, and what it draws from them.

    A cash account gets transactions, an investment account gets
    holdings; both end at ``_refresh``. The selection label rides
    here because the load is what resets it.
    """

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

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        # Claim this run. Two requests in flight can return out of order,
        # so a superseded one must not paint - otherwise the register can
        # settle on results for a prefix of what was typed.
        sequence = self._debounce.sequence
        api = get_session_state(self.page).api_client
        # A fresh table build below has nothing checked; a stale selection
        # from before this load would leave the bulk trigger showing a
        # count for rows that no longer exist on screen.
        self._selected_txn_ids = set()
        self._selected_amount = 0
        self._selected_trade_count = 0
        self._update_selection_label()
        if not self._categories:
            from app.services.finance.constants import UNCATEGORIZED_CATEGORY_NAMES

            cat_data = await api.get("/api/v1/finance/categories/options", cache_ttl=30)
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
                "/api/v1/finance/accounts",
                params={"page_size": 200},
                cache_ttl=30,
            )
            self._account_names = {
                a["id"]: a.get("name", "Account")
                for a in (
                    accounts.get("items", []) if isinstance(accounts, dict) else []
                )
            }
        params: dict[str, object] = {"page_size": self._register_page_size}
        from_date = range_start(self._range_days)
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

        builder = RegisterRowBuilder(
            all_accounts=all_accounts,
            account_names=self._account_names,
            category_picker=self._category_picker,
            merchant_picker=self._merchant_picker,
            on_tag_tap=self._filter_by_tag,
            split_category_cell=self._split_category_cell,
        )
        rows = [builder.row(kind, record) for kind, record in merged]

        def _expand(index: int, _merged: list = merged) -> ft.Control:
            kind, record = _merged[index]
            if kind == "trade":
                return _trade_expanded_content(record)
            return self._txn_expand_content(record)

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
