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

import asyncio
from collections.abc import Awaitable, Callable

import flet as ft

from app.components.frontend.controls import (
    ActionDropdown,
    MenuAction,
)
from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar
from app.core.config import settings

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


def _build_connect_menu(on_bank, on_brokerage) -> ActionDropdown | None:
    """The provider Connect menu, shared by the Accounts sidebar and the
    Connections tab header.

    Items appear whenever the provider capability is built into the stack
    (``settings.FINANCE_PLAID`` / ``FINANCE_SNAPTRADE``), not when
    credentials are set: hiding the menu on a fresh project with an empty
    ``.env`` made the feature's front door invisible. Missing credentials
    fail helpfully at click time instead (see the connect flows)."""
    actions: list[MenuAction] = []
    if settings.FINANCE_PLAID:
        actions.append(
            MenuAction("Connect a bank", ft.Icons.ACCOUNT_BALANCE_OUTLINED, on_bank)
        )
    if settings.FINANCE_SNAPTRADE:
        actions.append(
            MenuAction("Connect a brokerage", ft.Icons.SHOW_CHART, on_brokerage)
        )
    if not actions:
        return None
    return ActionDropdown("Connect", actions, tooltip="Connect an institution")


async def _connect_bank_flow(
    page: ft.Page, reload: Callable[[], Awaitable[None]]
) -> None:
    """Plaid Hosted Link: open Plaid's hosted connect page in a new tab, then
    poll server-side (~2.5 min) and reload the caller's view when the
    connection lands. (In sandbox mode the test credentials live on the
    Connections tab's Plaid card.)"""
    if not (settings.PLAID_CLIENT_ID and settings.PLAID_SECRET):
        ErrorSnackBar(
            "Plaid isn't configured yet: set PLAID_CLIENT_ID and PLAID_SECRET "
            "in .env, then restart."
        ).launch(page)
        return
    from app.components.frontend.state.session_state import get_session_state

    api = get_session_state(page).api_client
    started = await api.post("/api/v1/finance/plaid/hosted-link", json={})
    if not (isinstance(started, dict) and started.get("hosted_link_url")):
        ErrorSnackBar("Could not start Plaid.").launch(page)
        return
    page.launch_url(started["hosted_link_url"], web_window_name="_blank")
    SuccessSnackBar(
        "Complete the connection in the new tab; your accounts will "
        "appear here automatically."
    ).launch(page)
    link_token = started["link_token"]
    for _ in range(50):
        await asyncio.sleep(3)
        done = await api.post(
            "/api/v1/finance/plaid/hosted-link/complete",
            json={"link_token": link_token},
        )
        if isinstance(done, dict) and done.get("connections", 0) > 0:
            synced = sum(r.get("added", 0) for r in done.get("results", []))
            await reload()
            SuccessSnackBar(f"Bank connected — {synced} transactions synced.").launch(
                page
            )
            return


async def _connect_brokerage_flow(
    page: ft.Page, reload: Callable[[], Awaitable[None]]
) -> None:
    """SnapTrade connection portal: open it in a new tab, then poll
    server-side (~2.5 min) until the new authorization lands and reload the
    caller's view."""
    if not (settings.SNAPTRADE_CLIENT_ID and settings.SNAPTRADE_CONSUMER_KEY):
        ErrorSnackBar(
            "SnapTrade isn't configured yet: set SNAPTRADE_CLIENT_ID and "
            "SNAPTRADE_CONSUMER_KEY in .env, then restart."
        ).launch(page)
        return
    from app.components.frontend.state.session_state import get_session_state

    api = get_session_state(page).api_client
    started = await api.post("/api/v1/finance/snaptrade/connect", json={})
    if not (isinstance(started, dict) and "redirect_uri" in started):
        ErrorSnackBar("Could not start the brokerage connection.").launch(page)
        return
    if started["redirect_uri"]:
        page.launch_url(started["redirect_uri"], web_window_name="_blank")
        SuccessSnackBar(
            "Complete the connection in the new tab; your accounts will "
            "appear here automatically."
        ).launch(page)
    else:
        # Personal-key mode: no portal - brokerages are linked in
        # SnapTrade's dashboard and the poll below adopts what exists.
        SuccessSnackBar("Checking SnapTrade for your connected brokerages...").launch(
            page
        )
    for _ in range(50):
        await asyncio.sleep(3)
        done = await api.post("/api/v1/finance/snaptrade/connect/complete", json={})
        if isinstance(done, dict) and done.get("connections", 0) > 0:
            holdings = sum(r.get("holdings", 0) for r in done.get("results", []))
            await reload()
            SuccessSnackBar(
                f"Brokerage connected — {holdings} holdings synced."
            ).launch(page)
            return
