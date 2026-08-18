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
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.finance_modal.sidebar import (
    AccountsSidebar,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel import (
    TransactionsPanel,
)
from app.components.frontend.theme import AegisTheme as Theme


class AccountsTab(ft.Container):
    """The register tab: account sidebar + transaction/holdings detail."""

    def __init__(
        self,
        page: ft.Page,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__()
        self.expand = True
        panel = TransactionsPanel(page, account_filter, register_filter_listener)
        # Composite, not a FinancePanel: it has no _load of its own.
        # A dialog-level revisit still has to reach the register it
        # hosts, or edits made on other tabs (a payee named in
        # Review) go stale here silently - the same drift class the
        # base exists to kill.
        self._panel = panel
        sidebar = AccountsSidebar(
            page,
            on_select=panel.select,
            on_import_transactions=panel.open_transactions_import_picker,
            on_import_investments=panel.open_investments_import_picker,
        )
        panel.set_reload_hook(sidebar.reload)
        self.content = ft.Row([sidebar, panel], spacing=0, expand=True)

    def refresh_on_revisit(self) -> None:
        if self._panel.page:
            self._panel.page.run_task(self._panel._load)


def _list_card(
    title: str,
    rows: list[ft.Control],
    *,
    on_click: Callable[[], None] | None = None,
) -> ft.Control:
    """Card chrome around a list of rows, matching the chart cards.

    The ranked-bar cards draw their own surface; a plain list needs the
    same one, or it reads as loose text beside boxed neighbours.

    ``on_click`` makes the whole card a button (ink ripple, no arg) - for
    a card that is a preview of something actionable elsewhere, like the
    Uncategorized card opening its own dialog.
    """
    card = ft.Container(
        content=ft.Column(
            [SecondaryText(title, size=Theme.Typography.BODY_SMALL), *rows],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=Theme.Spacing.MD,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.border.all(0.5, ft.Colors.OUTLINE),
        border_radius=Theme.Components.CARD_RADIUS,
    )
    if on_click is not None:
        card.on_click = lambda _e: on_click()
        card.ink = True
    return card


def _overview_row(label: str, sublabel: str, amount: int, color: str) -> ft.Control:
    """A labeled amount row for the Overview breakdowns (group totals + spending
    by category). One shape, two callers."""
    return ft.Container(
        content=ft.Row(
            [
                PrimaryText(
                    label,
                    size=Theme.Typography.BODY,
                    color=Theme.Colors.TEXT_PRIMARY,
                    weight=ft.FontWeight.W_500,
                    expand=True,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                SecondaryText(
                    sublabel,
                    size=Theme.Typography.CAPTION,
                    color=Theme.Colors.TEXT_SECONDARY,
                ),
                NumericText(
                    _usd(amount),
                    size=Theme.Typography.BODY,
                    color=color,
                    weight=ft.FontWeight.W_600,
                ),
            ],
            spacing=Theme.Spacing.LG,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(
            vertical=Theme.Spacing.SM, horizontal=Theme.Spacing.MD
        ),
        border=ft.border.only(bottom=ft.BorderSide(1, Theme.Colors.BORDER_SUBTLE)),
    )
