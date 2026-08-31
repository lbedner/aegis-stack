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
from app.components.frontend.dashboard.modals.finance_modal.no_payee_panel import (
    NoPayeePanel,
)
from app.components.frontend.dashboard.modals.finance_modal.pending_changes import (
    PendingChangesSection,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_panel import (
    UncategorizedPanel,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.theme import AegisTheme as Theme


class ReviewTab(FinancePanel):
    """Sub-tabs of things waiting on a decision, not one screen.

    - Approvals: assistant proposals from the propose/approve queue -
      the Overview banner points here.
    - Uncategorized: the same work queue as the Overview card's dialog
      (``UncategorizedPanel``, own instance, own data load - not a link
      to that dialog, just the same reusable class). Shares the outer
      dialog's one ``AccountFilter`` AND its one filter button (pinned
      above the tab strip, not rebuilt per tab) - a narrower view set
      there keeps applying here, live, via ``register_filter_listener``.
    - Attention: ``AttentionTab`` (moved here from its own top-level tab -
      analyst narration over the rule findings it was written from).
      ``analyst_enabled`` has to be threaded through from
      ``FinanceDetailDialog`` so ``with_notes`` matches what the metadata
      actually reports instead of silently defaulting to a different
      value.

    Nested ``PulseTabs`` (the same tab styling the outer Finance modal
    uses for Overview/Accounts/Review/...) rather than stacking sections
    in one scroll - unrelated review queues sharing a screen made it
    unclear which list you were even looking at.
    """

    def __init__(
        self,
        page: ft.Page,
        *,
        analyst_enabled: bool = False,
        account_filter: AccountFilter | None = None,
        register_filter_listener: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(page, account_filter, register_filter_listener, expand=True)
        # No padding here - it belongs on each sub-tab's own content, same
        # as SettingsTab (its wrapper carries none; ConnectionsTab and
        # CategoriesTab each pad themselves). Padding on this outer
        # Container would sit OUTSIDE the nested PulseTabs, widening the
        # gap between it and the Finance modal's own tab bar above it.
        self._uncategorized = UncategorizedPanel(
            page,
            width=None,
            account_filter=account_filter,
            register_filter_listener=register_filter_listener,
        )
        self._uncategorized.padding = ft.padding.all(Theme.Spacing.LG)
        # Same shared AccountFilter (and the same live re-filtering) the
        # Uncategorized queue beside it uses - a narrower account view
        # follows you across every sub-tab here.
        self._no_payee = NoPayeePanel(
            page,
            account_filter=account_filter,
            register_filter_listener=register_filter_listener,
        )
        self._no_payee.padding = ft.padding.all(Theme.Spacing.LG)

        # Deferred: finance_attention_tab.py imports _refresh_row FROM this
        # module, so a top-level import here would be a cycle.
        from app.components.frontend.dashboard.modals.finance_attention_tab import (
            AttentionTab,
        )

        self._attention = AttentionTab(page, with_notes=analyst_enabled)

        # Approvals lead: assistant proposals are the highest-stakes
        # queue here (they change the ledger on approval), and Overview
        # only points at this sub-tab via its banner.
        self._pending = PendingChangesSection(
            page,
            empty_message=(
                "Nothing awaiting your approval. Proposals your "
                "assistant files in chat land here too."
            ),
        )
        self._approvals = ft.Container(
            content=ft.Column(
                [self._pending], scroll=ft.ScrollMode.AUTO, expand=True
            ),
            padding=ft.padding.all(Theme.Spacing.LG),
            expand=True,
        )

        self.content = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Approvals", content=self._approvals),
                ft.Tab(text="Uncategorized", content=self._uncategorized),
                ft.Tab(text="No payee", content=self._no_payee),
                ft.Tab(text="Attention", content=self._attention),
            ],
            expand=True,
        )

    def refresh_on_revisit(self) -> None:
        """Dialog revisit hook (and the Overview banner's jump): the
        approvals queue re-reads so a just-filed proposal is there."""
        self._pending.refresh_on_revisit()
