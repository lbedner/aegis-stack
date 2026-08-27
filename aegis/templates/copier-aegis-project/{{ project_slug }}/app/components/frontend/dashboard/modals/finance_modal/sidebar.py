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

from app.components.frontend.controls import (
    BaseIconButton,
    NumericText,
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.components.frontend.dashboard.modals.finance_modal.connect import (
    _build_connect_menu,
    _connect_bank_flow,
    _connect_brokerage_flow,
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
    _ACCOUNT_GROUPS,
    _ADD_ACCOUNT_TYPES,
    _LIABILITY_ACCOUNT_TYPES,
    _SIDEBAR_WIDTH,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _account_display_balance,
    _balance_color,
    _group_for,
    _liability_line,
    _parse_dollars,
    _usd,
)
from app.components.frontend.dashboard.modals.finance_modal.import_summary import (
    _import_menu,
)
from app.components.frontend.theme import AegisTheme as Theme


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
            BaseIconButton(
                self.reload,
                icon=ft.Icons.REFRESH,
                icon_size=18,
                tooltip="Refresh accounts",
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
                    SecondaryText(
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
        name = PrimaryText(
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
                    SecondaryText(
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
        data = await api.get(
            "/api/v1/finance/accounts", params={"page_size": 200}, cache_ttl=30
        )
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
