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
)
from app.components.frontend.dashboard.modals.finance_modal.account_header import (
    panel_detail_header,
)
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _INVESTMENT_TYPES,
    _REGISTER_PAGE_SIZE,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    TagApplyMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
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
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.load import (
    RegisterLoadMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.manage import (
    ManageAccountMixin,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.splits_flow import (
    SplitsFlowMixin,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    DateRangeChips,
)
from app.components.frontend.theme import AegisTheme as Theme


class TransactionsPanel(
    RegisterLoadMixin,
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
