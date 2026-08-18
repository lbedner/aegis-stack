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
    ActionMenu,
    ActionMenuItem,
    ConfirmDialog,
    DataTable,
    DataTableColumn,
    ExpandArrow,
    PrimaryText,
    SecondaryText,
    StatusTag,
)
from app.components.frontend.controls.snack_bar import SuccessSnackBar
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
from app.components.frontend.dashboard.modals.finance_modal.connect import (
    _build_connect_menu,
    _connect_bank_flow,
    _connect_brokerage_flow,
)
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _PLAID_SANDBOX_CREDENTIALS,
    _STATUS_STYLE,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _account_display_balance,
    _amount_cell,
    _refresh_row,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import (
    EmptyStatePlaceholder,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.config import settings
from app.services.system.models import ComponentStatusType


def _status_style(status: str) -> tuple[str, ComponentStatusType]:
    return _STATUS_STYLE.get(
        status,
        (status.replace("_", " ").title(), ComponentStatusType.INFO),
    )


def _connection_title(conn: dict) -> str:
    if conn.get("label"):
        return conn["label"]
    provider = (conn.get("provider") or "connection").title()
    environment = (conn.get("environment") or "").title()
    return f"{provider} · {environment}" if environment else provider


class ConnectionCard(ft.Container):
    """Collapsible card for the Connections grid.

    One anatomy for everything in the grid — provider connections, the
    manual/imported bucket, and the Plaid sandbox helper: a header row
    (expand arrow + bold title + caption subtitle) that toggles the body,
    an optional ``Tag`` in the status slot, an optional trailing action
    control, and a ``DataTable`` body.
    """

    def __init__(
        self,
        *,
        title: str,
        subtitle: str | None = None,
        tag: ft.Control | None = None,
        action: ft.Control | None = None,
        columns: list[DataTableColumn],
        rows: list[list[ft.Control]],
        empty_message: str,
        on_row_click: Callable[[int], None] | None = None,
        expanded: bool = False,
    ) -> None:
        super().__init__()
        self._arrow = ExpandArrow(expanded=expanded)
        self._table = ft.Container(
            content=DataTable(
                columns=columns,
                rows=rows,
                empty_message=empty_message,
                on_row_click=on_row_click,
            ),
            visible=expanded,
        )
        title_col = ft.Column(
            [
                PrimaryText(
                    title,
                    size=Theme.Typography.BODY,
                    weight=ft.FontWeight.W_600,
                ),
                SecondaryText(subtitle or "", size=Theme.Typography.CAPTION),
            ],
            spacing=2,
            expand=True,
        )
        header_bits: list[ft.Control] = [
            ft.Container(
                content=ft.Row(
                    [self._arrow, title_col],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=Theme.Spacing.XS,
                ),
                on_click=self._toggle,
                ink=True,
                expand=True,
                border_radius=Theme.Components.BUTTON_RADIUS,
            )
        ]
        if tag is not None:
            header_bits.append(tag)
        if action is not None:
            header_bits.append(action)
        elif tag is not None:
            # Reserve the action (kebab) slot so tags align in a column
            # across cards that do and don't carry an action.
            header_bits.append(ft.Container(width=40))
        self.content = ft.Column(
            [
                ft.Row(header_bits, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self._table,
            ],
            spacing=Theme.Spacing.SM,
        )
        # Two fluid columns on wide viewports, one on narrow: the grid fills
        # the tab's width, so header controls (Connect / refresh) sit over
        # card content instead of dead space past a fixed-width grid.
        self.col = {"sm": 12, "lg": 6}
        self.padding = ft.padding.all(Theme.Spacing.MD)
        self.bgcolor = Theme.Colors.SURFACE_1
        self.border = ft.border.all(1, Theme.Colors.BORDER_SUBTLE)
        self.border_radius = Theme.Components.CARD_RADIUS

    def _toggle(self, _e: ft.ControlEvent) -> None:
        self._arrow.toggle()
        self._table.visible = self._arrow.expanded
        self._arrow.update()
        self._table.update()


def _plaid_sandbox_card(page: ft.Page) -> ConnectionCard:
    """The Plaid sandbox helper, composed from the same ``ConnectionCard``
    as every provider card. Clicking a credential row copies its value."""

    def _copy_row(index: int) -> None:
        label, value = _PLAID_SANDBOX_CREDENTIALS[index]
        page.set_clipboard(value)
        SuccessSnackBar(f"{label} copied").launch(page)

    return ConnectionCard(
        title="Plaid",
        subtitle="Test credentials for the connect screen  ·  click a row to copy",
        tag=StatusTag(status=ComponentStatusType.WARNING, text="Sandbox"),
        columns=[
            DataTableColumn("Credential"),
            DataTableColumn("Value", width=180, alignment="right"),
        ],
        rows=[
            [TableNameText(label), TableCellText(value)]
            for label, value in _PLAID_SANDBOX_CREDENTIALS
        ],
        empty_message="No credentials",
        on_row_click=_copy_row,
    )


class ConnectionsTab(FinancePanel):
    """See every account and how it's connected, and disconnect at any time.

    One card per provider connection (its accounts nested inside, with a
    Disconnect button); a final "Manual & imported" card for accounts that have
    no connection."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(page)
        self.expand = True
        self.padding = ft.padding.all(Theme.Spacing.LG)
        self._body = ft.Column(
            spacing=Theme.Spacing.MD, scroll=ft.ScrollMode.AUTO, expand=True
        )
        connect = _build_connect_menu(
            lambda e: e.page.run_task(self._connect_bank),
            lambda e: e.page.run_task(self._connect_brokerage),
        )
        self.content = ft.Column(
            [
                _refresh_row(
                    lambda e: e.page.run_task(self._load),
                    "Refresh connections",
                    leading=[connect] if connect is not None else None,
                ),
                self._body,
            ],
            spacing=Theme.Spacing.MD,
            expand=True,
        )

    async def _connect_bank(self) -> None:
        await _connect_bank_flow(self.page, self._load)

    async def _connect_brokerage(self) -> None:
        await _connect_brokerage_flow(self.page, self._load)

    def _card(
        self,
        title: str,
        accounts: list[dict],
        *,
        status: str | None = None,
        subtitle: str | None = None,
        on_disconnect=None,
    ) -> ft.Control:
        # Aligned columns (Account / Type / Balance) — same DataTable the
        # Accounts tab uses for transactions, so the type reads as a quiet
        # column instead of a loud per-row pill.
        tag = None
        if status is not None:
            label, severity = _status_style(status)
            # Same dot indicator the rest of the Overseer uses for status.
            tag = StatusTag(status=severity, text=label)
        action = None
        if on_disconnect is not None:
            # Kebab menu keeps destructive actions out of the resting view.
            action = ActionMenu(
                [
                    ActionMenuItem(
                        "Disconnect",
                        ft.Icons.LINK_OFF,
                        lambda e: e.page.run_task(on_disconnect),
                        destructive=True,
                    )
                ]
            )
        return ConnectionCard(
            title=title,
            subtitle=subtitle,
            tag=tag,
            action=action,
            columns=[
                DataTableColumn("Account"),
                DataTableColumn("Type", width=120),
                DataTableColumn("Balance", width=130, alignment="right"),
            ],
            rows=[
                [
                    TableNameText(account.get("name", "")),
                    TableCellText(
                        (account.get("account_type") or "").replace("_", " ").title()
                    ),
                    _amount_cell(_account_display_balance(account)),
                ]
                for account in accounts
            ],
            empty_message="No accounts.",
        )

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        conn_data = await api.get("/api/v1/finance/connections")
        acct_data = await api.get(
            "/api/v1/finance/accounts", params={"page_size": 200}, cache_ttl=30
        )
        connections = conn_data.get("items", []) if isinstance(conn_data, dict) else []
        accounts = acct_data.get("items", []) if isinstance(acct_data, dict) else []

        by_connection: dict[int, list[dict]] = {}
        unconnected: list[dict] = []
        for account in accounts:
            cid = account.get("connection_id")
            if cid is None:
                unconnected.append(account)
            else:
                by_connection.setdefault(cid, []).append(account)

        cards: list[ft.Control] = []
        for conn in connections:
            conn_accounts = by_connection.get(conn["id"], [])
            synced = conn.get("last_successful_sync_at")
            synced_text = (
                f"Last synced {str(synced).split('T')[0]}" if synced else "Never synced"
            )
            subtitle = (
                f"{len(conn_accounts)} account"
                f"{'s' if len(conn_accounts) != 1 else ''}  ·  {synced_text}"
            )
            cards.append(
                self._card(
                    _connection_title(conn),
                    conn_accounts,
                    status=conn.get("status"),
                    subtitle=subtitle,
                    on_disconnect=self._disconnect_handler(conn, len(conn_accounts)),
                )
            )

        if unconnected:
            cards.append(
                self._card(
                    "Manual & imported",
                    unconnected,
                    subtitle="Not connected — added manually or from a file import.",
                )
            )

        # Sandbox helper rides the same grid as the provider cards, styled
        # identically, so the Plaid test credentials are always reachable
        # while a hosted connect screen is asking for them.
        if settings.FINANCE_PLAID and settings.PLAID_ENV == "sandbox":
            cards.append(_plaid_sandbox_card(self.page))

        self._body.controls.clear()
        if cards:
            self._body.controls.append(
                ft.ResponsiveRow(
                    cards,
                    spacing=Theme.Spacing.MD,
                    run_spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                )
            )
        else:
            self._body.controls.append(
                EmptyStatePlaceholder(message="No accounts or connections yet.")
            )
        if self._body.page is not None:
            self._body.update()

    def _disconnect_handler(self, conn: dict, account_count: int):
        """An async no-arg click handler (PulseButton's contract) that opens the
        disconnect confirmation for this connection."""

        async def _handler() -> None:
            self._open_disconnect(conn, account_count)

        return _handler

    def _open_disconnect(self, conn: dict, account_count: int) -> None:
        noun = f"{account_count} account{'s' if account_count != 1 else ''}"
        ConfirmDialog(
            page=self.page,
            title="Disconnect",
            message=(
                f"Disconnect {_connection_title(conn)}? This removes {noun} and "
                "stops syncing. Transaction history is kept and not deleted."
            ),
            confirm_text="Disconnect",
            destructive=True,
            on_confirm=lambda: self._do_disconnect(conn["id"]),
        ).show()

    async def _do_disconnect(self, connection_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/connections/{connection_id}")
        SuccessSnackBar("Disconnected.").launch(self.page)
        await self._load()
