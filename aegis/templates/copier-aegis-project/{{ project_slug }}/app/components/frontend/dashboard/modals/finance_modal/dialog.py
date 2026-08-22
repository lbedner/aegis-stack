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

from app.components.frontend.controls.tabs import PulseTabs
from app.components.frontend.dashboard.cards.card_utils import get_status_detail
from app.components.frontend.dashboard.modals.base_detail_popup import BaseDetailPopup

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
from app.components.frontend.dashboard.modals.finance_modal.accounts_tab import (
    AccountsTab,
)
from app.components.frontend.dashboard.modals.finance_modal.budget_panel import (
    BudgetPanel,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import (
    AccountFilterButton,
)
from app.components.frontend.dashboard.modals.finance_modal.overview_tab import (
    OverviewTab,
)
from app.components.frontend.controls.chat import ChatPanel
from app.components.frontend.dashboard.modals.finance_modal.review_tab import ReviewTab
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title


class FinanceDetailDialog(BaseDetailPopup):
    """Finance detail modal — a tabbed workspace.

    Six tabs you would open on a normal day (Overview, Accounts,
    Bills & Income, Projected, Budget, Review) plus a gear holding the
    setup surfaces. Review is itself tabbed (Uncategorized / Transfers /
    Attention - Attention merges the analyst note with the rule findings
    it was written from); Connections and Categories live behind the gear.
    """

    def __init__(self, component_data: ComponentStatus, page: ft.Page) -> None:
        from app.components.frontend.dashboard.modals.finance_recurring_tab import (
            ProjectionPanel,
            RecurringTab,
        )
        from app.components.frontend.dashboard.modals.finance_settings_tab import (
            SettingsTab,
        )

        # The analyst only exists in builds that selected the AI service, and
        # the service reports that in its status metadata. Without it the
        # Attention sub-tab (under Review) is the findings alone rather than
        # an empty slot.
        analyst_enabled = bool((component_data.metadata or {}).get("analyst_enabled"))

        # One account-selection shared across every tab that consumes it
        # (Overview, Review's embedded UncategorizedPanel) - dialog-owned
        # so a narrower view follows the user from tab to tab. The FILTER
        # BUTTON itself is dialog-owned too, one instance shown once above
        # the tab strip rather than one per consuming tab: two separate
        # buttons sharing one AccountFilter (the original design) meant
        # two separate menus to keep visually in sync, and the second one
        # only got redrawn on ITS OWN first load, so a change made via one
        # button left the other's dots/trigger label stale until its next
        # unrelated reload (confirmed live, on the Review tab). One button
        # can't drift from itself.
        #
        # ADOPTED from the process-level view-state store, not constructed:
        # this dialog is cached on ``page.data`` and dies with the Flet
        # session (a page reload; every hot-reload in dev), and a filter
        # that silently resets to "All accounts" makes the same screen
        # tell a different story than it told a minute ago - confirmed
        # live, on the projection's sign. The store hands every recreation
        # the SAME AccountFilter instance, so mutations carry forward.
        from app.components.frontend.state.finance_view_state import (
            SOLO_OWNER_KEY,
            finance_view_state,
        )
        from app.components.frontend.state.session_state import get_session_state

        user = getattr(get_session_state(page), "current_user", None)
        owner_key = (
            str(user["id"])
            if isinstance(user, dict) and user.get("id") is not None
            else SOLO_OWNER_KEY
        )
        self._account_filter = finance_view_state(owner_key=owner_key).account_filter
        self._account_items: list[dict] = []
        # Called after every filter change, in registration order, so a
        # tab reloads even while it's not the one currently on screen -
        # otherwise switching back to an already-built (lazy-loaded) tab
        # after changing the filter elsewhere would show stale data until
        # some OTHER trigger happened to reload it.
        self._filter_listeners: list[Callable[[], None]] = []
        self._account_filter_button = AccountFilterButton(
            on_change=self._on_account_filter_change,
            account_filter=self._account_filter,
        )

        # Ordered by how often you look at it, summary first; Review sits
        # after Projected, last of the reading tabs, since it's a queue you
        # work through rather than numbers you read - and now hosts
        # Attention as one of its own sub-tabs (Uncategorized / Transfers /
        # Attention) rather than that living as a sixth top-level tab of
        # its own. Connections and Categories are setup, not reading, so
        # they sit behind the gear at the end. The gear is a Tab with an
        # icon and no text, so it costs a few pixels and nothing you use
        # daily gets nested.
        factories: list[tuple[str, Callable[[], ft.Control], str | None]] = [
            (
                "Overview",
                lambda: OverviewTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Accounts",
                lambda: AccountsTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Bills & Income",
                lambda: RecurringTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Projected",
                lambda: ProjectionPanel(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Budget",
                lambda: BudgetPanel(
                    page, self._account_filter, self.register_filter_listener
                ),
                None,
            ),
            (
                "Review",
                lambda: ReviewTab(
                    page,
                    analyst_enabled=analyst_enabled,
                    account_filter=self._account_filter,
                    register_filter_listener=self.register_filter_listener,
                ),
                None,
            ),
        ]
        # Chat rides the AI service: without it there is no chat API to
        # speak to, so the tab simply does not exist rather than erroring.
        if analyst_enabled:
            # The snapshot memory module maps chat user ids to finance
            # owners; the analyst's standalone id ("0" = unscoped owner)
            # is the one id that resolves in a single-tenant install. The
            # generic default ("api-user") is unparseable and would skip
            # the briefing entirely.
            from app.services.finance.domains.detection.analyst.shared import (
                STANDALONE_USER_ID,
            )

            factories.append(
                (
                    "Chat",
                    lambda: ChatPanel(
                        agent_slug="finance-assistant",
                        surface="finance",
                        agent_name="Finance Assistant",
                        user_id=STANDALONE_USER_ID,
                        placeholder=(
                            "Ask about your accounts, spending, envelopes, "
                            "goals, or holdings. Answers that need math are "
                            "computed from your real data."
                        ),
                    ),
                    None,
                )
            )
        factories.append(
            (
                "",
                lambda: SettingsTab(
                    page, self._account_filter, self.register_filter_listener
                ),
                ft.Icons.SETTINGS_OUTLINED,
            )
        )

        self._lazy_contents = [_LazyTabContent(factory) for _, factory, _ in factories]
        tab_list = [
            ft.Tab(text=name or None, icon=icon, content=content)
            for (name, _, icon), content in zip(
                factories, self._lazy_contents, strict=False
            )
        ]

        def _on_tab_change(event: ft.ControlEvent) -> None:
            index = int(event.control.selected_index or 0)
            if 0 <= index < len(self._lazy_contents):
                lazy = self._lazy_contents[index]
                if lazy.ensure_built():
                    # A revisit. Panels fetch once in did_mount, so a
                    # change made on ANOTHER tab (confirming a bill that
                    # should suppress a budget suggestion) went stale
                    # silently until the modal was reopened. A panel that
                    # opts in refetches; its data is a cheap read, so no
                    # visible "refresh" chrome is needed.
                    refresh = getattr(lazy.content, "refresh_on_revisit", None)
                    if callable(refresh):
                        refresh()

        tabs = PulseTabs(
            selected_index=0,
            tabs=tab_list,
            expand=True,
            on_change=_on_tab_change,
        )
        # The initial tab is visible immediately; build it now.
        self._lazy_contents[0].ensure_built()
        # Pinned above the tab strip, right-aligned - visible (and the
        # SAME control) no matter which tab is selected, rather than
        # living inside whichever tab happened to build it first.
        filter_row = ft.Row(
            [ft.Container(expand=True), self._account_filter_button],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        super().__init__(
            page=page,
            component_data=component_data,
            title_text=get_component_title("service_finance"),
            subtitle_text="Accounts, transactions, and investments",
            sections=[filter_row, tabs],
            scrollable=False,
            width=1600,
            height=900,
            status_detail=get_status_detail(component_data),
        )

    def did_mount(self) -> None:
        if self.page:
            self.page.run_task(self._load_accounts)

    def register_filter_listener(self, callback: Callable[[], None]) -> None:
        """A consuming tab's own reload trigger, called after every
        filter change - see ``_filter_listeners`` for why this covers
        tabs that aren't currently on screen too."""
        self._filter_listeners.append(callback)

    async def _load_accounts(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(
            "/api/v1/finance/accounts", params={"page_size": 200}, cache_ttl=30
        )
        self._account_items = data.get("items", []) if isinstance(data, dict) else []
        self._account_filter_button.set_accounts(self._account_items)

    def _on_account_filter_change(self) -> None:
        # Redraws THIS button's own dots/trigger label - there's only one
        # now, but it still doesn't repaint itself just because .selected
        # changed underneath it.
        self._account_filter_button.set_accounts(self._account_items)
        for listener in self._filter_listeners:
            listener()


class _LazyTabContent(ft.Container):
    """Builds a tab's content on first visit instead of at modal open.

    Seven tabs each fetching their world the moment the modal opens is why
    the modal felt heavy: every open paid for every tab. Content is built
    (and its ``did_mount`` loads fire) only when the tab is first selected.
    """

    def __init__(self, factory: Callable[[], ft.Control]) -> None:
        super().__init__(expand=True)
        self._factory = factory
        self._built = False

    def ensure_built(self) -> bool:
        """Build on first visit. Returns True when the tab was ALREADY
        built - a revisit, where a panel's data may have gone stale."""
        if self._built:
            return True
        self._built = True
        self.content = self._factory()
        if self.page is not None:
            self.update()
        return False
