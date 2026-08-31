"""The register core: load, render, selection, search, holdings.

The heavy flows live in the sibling mixins (``imports_flow``,
``declare``, ``bulk``, ``manage``); this module owns the panel's state,
constructor and the load/selection spine they all call back into.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from app.components.frontend.controls import (
    DataTable,
    DataTableColumn,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.debounce import Debouncer
from app.components.frontend.controls.form_fields import FormTextField
from app.components.frontend.controls.pickers import (
    BulkActionTrigger,
    CategoryPickerButton,
    MerchantPickerButton,
    TagPickerButton,
    picker_trigger_cell,
)
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.table import (
    TableCellText,
    TableNameText,
)
from app.components.frontend.dashboard.modals.finance_modal.account_header import (
    panel_detail_header,
)
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _DENSE_ROW_HEIGHT,
    _INVESTMENT_TYPES,
    _REGISTER_PAGE_SIZE,
    _TXN_CATEGORY_COLUMN_WIDTH,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    TagApplyMixin,
    range_start,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
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
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.bulk import (
    BulkActionsMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.declare import (
    DeclareMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.imports_flow import (
    ImportsFlowMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.manage import (
    ManageAccountMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.splits_flow import (
    SplitsFlowMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    register_columns,
    register_count_label,
    transaction_tag_chips,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
    EmptyStatePlaceholder,
    date_cell,
)
from app.components.frontend.theme import AegisTheme as Theme


class TransactionsPanel(
    TagApplyMixin,
    ImportsFlowMixin,
    DeclareMixin,
    BulkActionsMixin,
    ManageAccountMixin,
    SplitsFlowMixin,
    TransactionsPanelState,
):
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
        self._title = H3Text(
            "All Accounts",
            color=Theme.Colors.TEXT_PRIMARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._subtitle = SecondaryText(
            "",
            size=Theme.Typography.BODY_SMALL,
            color=Theme.Colors.TEXT_SECONDARY,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        # Beside the count, not under the table: a footer costs a row's
        # height, and the count line already tells this story.
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
        # domains/domains/detection/recurring/cadence.py's _payee_key.
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
            panel_detail_header(self, account) if is_account else None
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

    def _on_range_change(self, days: int) -> None:
        self._range_days = days
        is_investment = self._account is not None and (
            self._account.get("account_type") in _INVESTMENT_TYPES
        )
        self.page.run_task(self._load_holdings if is_investment else self._load)

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

        def _category_cell(record: dict) -> ft.Control:
            # Re-categorizing an ALREADY-categorized transaction - unlike
            # UncategorizedPanel's placeholder, this shows the current
            # pick as the trigger's own label, same idea as any other
            # "click a value to change it" field.
            txn_id = record.get("id")
            if record.get("is_split") and record.get("splits"):
                return self._split_category_cell(record)
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
            # changing later (domains/domains/detection/recurring/cadence.py's _payee_key).
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
