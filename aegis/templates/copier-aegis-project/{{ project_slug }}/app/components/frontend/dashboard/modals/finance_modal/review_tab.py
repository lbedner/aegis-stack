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
    PrimaryText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.record_detail import (
    RecordDetailDialog,
)
from app.components.frontend.controls.snack_bar import SuccessSnackBar
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
from app.components.frontend.dashboard.modals.finance_modal.constants import (
    _TRANSACTION_COLLAPSED_SECTIONS,
)
from app.components.frontend.dashboard.modals.finance_modal.filters import AccountFilter
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _amount_cell,
    _refresh_row,
)
from app.components.frontend.dashboard.modals.finance_modal.no_payee_panel import (
    NoPayeePanel,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    transaction_detail_hero,
    transaction_detail_sections,
    transaction_tooltip,
)
from app.components.frontend.dashboard.modals.finance_modal.uncategorized_panel import (
    UncategorizedPanel,
)
from app.components.frontend.dashboard.modals.finance_panel import FinancePanel
from app.components.frontend.dashboard.modals.modal_sections import (
    EmptyStatePlaceholder,
)
from app.components.frontend.theme import AegisTheme as Theme


class ReviewTab(FinancePanel):
    """Three sub-tabs of things waiting on a decision, not one screen.

    - Uncategorized: the same work queue as the Overview card's dialog
      (``UncategorizedPanel``, own instance, own data load - not a link
      to that dialog, just the same reusable class). Shares the outer
      dialog's one ``AccountFilter`` AND its one filter button (pinned
      above the tab strip, not rebuilt per tab) - a narrower view set
      there keeps applying here, live, via ``register_filter_listener``.
    - Transfers: suggested transfers - pairs the detector matched but
      wasn't sure enough about to auto-hide (so nothing is silently
      removed from spend). Confirm excludes both legs from reports;
      Reject keeps them as normal spend/income and the pair is never
      suggested again.
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
        self._body = ft.Column(
            spacing=Theme.Spacing.MD, scroll=ft.ScrollMode.AUTO, expand=True
        )
        transfers_view = ft.Container(
            content=ft.Column(
                [
                    _refresh_row(
                        lambda e: e.page.run_task(self._load), "Refresh suggestions"
                    ),
                    self._body,
                ],
                spacing=0,
                expand=True,
            ),
            padding=ft.padding.all(Theme.Spacing.LG),
            expand=True,
        )
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

        self.content = PulseTabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Uncategorized", content=self._uncategorized),
                ft.Tab(text="No payee", content=self._no_payee),
                ft.Tab(text="Transfers", content=transfers_view),
                ft.Tab(text="Attention", content=self._attention),
            ],
            expand=True,
        )

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        data = await api.get(
            "/api/v1/finance/transfers", params={"status": "suggested"}
        )
        suggestions = data.get("items", []) if isinstance(data, dict) else []
        acct_data = await api.get(
            "/api/v1/finance/accounts", params={"page_size": 200}, cache_ttl=30
        )
        accounts = acct_data.get("items", []) if isinstance(acct_data, dict) else []
        name_by_id = {a["id"]: a.get("name", "Account") for a in accounts}

        self._body.controls.clear()
        if not suggestions:
            self._body.controls.append(
                EmptyStatePlaceholder(
                    message="No transfers to review. Matches we're confident "
                    "about are paired automatically."
                )
            )
        else:
            count = len(suggestions)
            self._body.controls.append(
                SecondaryText(
                    f"{count} possible transfer{'s' if count != 1 else ''} to review"
                )
            )
            self._body.controls.extend(
                self._row(item, name_by_id) for item in suggestions
            )
        if self._body.page is not None:
            self._body.update()

    def _row(self, item: dict, name_by_id: dict) -> ft.Control:
        frm = name_by_id.get(item.get("from_account_id"), "Account")
        to = name_by_id.get(item.get("to_account_id"), "Account")
        # Lead with the two legs' descriptions — that's what makes a real
        # transfer ("AMEX EPAYMENT -> PAYMENT RECEIVED") obvious from a
        # coincidence ("Starbucks -> INTRST PYMNT"). Each leg is clickable and
        # opens its full transaction detail (same dialog as the register).
        from_txn = item.get("from_transaction") or {}
        to_txn = item.get("to_transaction") or {}
        transfer_date = str(item.get("transfer_date") or "").split("T")[0]
        confidence = item.get("confidence")
        meta_bits = [f"{frm} -> {to}", transfer_date]
        if confidence is not None:
            meta_bits.append(f"{confidence}% match")
        if item.get("is_credit_card_payment"):
            meta_bits.append("card payment")
        header = ft.Row(
            [
                self._leg(from_txn, frm),
                SecondaryText("→"),
                self._leg(to_txn, to),
                ft.Container(expand=True),
                _amount_cell(item.get("amount") or 0),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=Theme.Spacing.SM,
        )
        actions = ft.Row(
            [
                PulseButton(
                    on_click_callable=self._action(item["id"], "confirm"),
                    text="Confirm",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=self._action(item["id"], "reject"),
                    text="Reject",
                    variant="stop",
                    compact=True,
                ),
            ],
            spacing=Theme.Spacing.SM,
        )
        return ft.Container(
            content=ft.Column(
                [
                    header,
                    ft.Row(
                        [
                            SecondaryText("  ·  ".join(meta_bits)),
                            ft.Container(expand=True),
                            actions,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=Theme.Spacing.XS,
            ),
            padding=ft.padding.all(Theme.Spacing.MD),
            bgcolor=Theme.Colors.SURFACE_1,
            border=ft.border.all(1, Theme.Colors.BORDER_SUBTLE),
            border_radius=Theme.Components.CARD_RADIUS,
        )

    def _leg(self, txn: dict, account_name: str) -> ft.Control:
        """A clickable leg description that opens its full transaction
        detail (same field mapper as the register) - the one remaining
        RecordDetailDialog use in this module. Not a DataTable row (it's a
        transfer-match card, two legs side by side), so there's no row to
        expand inline the way every other transaction surface now does."""
        label = (txn.get("name") if txn else None) or account_name
        text = PrimaryText(label, weight=Theme.Typography.WEIGHT_SEMIBOLD)
        if not txn:
            return text
        return ft.Container(
            content=text,
            on_click=lambda _e, t=txn: RecordDetailDialog(
                self.page,
                "Transaction detail",
                transaction_detail_sections(t),
                hero=transaction_detail_hero(t),
                collapsed_sections=_TRANSACTION_COLLAPSED_SECTIONS,
            ).show(),
            ink=True,
            border_radius=Theme.Components.BUTTON_RADIUS,
            padding=ft.padding.symmetric(horizontal=Theme.Spacing.XS),
            tooltip=transaction_tooltip(txn),
        )

    def _action(self, transfer_id: int, action: str):
        """No-arg async click handler (PulseButton's contract)."""

        async def _handler() -> None:
            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            await api.post(f"/api/v1/finance/transfers/{transfer_id}/{action}")
            message = (
                "Marked as a transfer." if action == "confirm" else "Kept as spending."
            )
            SuccessSnackBar(message).launch(self.page)
            await self._load()

        return _handler
