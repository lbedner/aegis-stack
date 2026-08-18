"""Bulk curation over the selection: categorize, payee, tags, delete.

One mixin of ``TransactionsPanel`` - state contract in ``base``.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls import ConfirmDialog
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    apply_category_picks,
    create_category,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import _usd
from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.base import (
    TransactionsPanelState,
)
from app.components.frontend.dashboard.modals.finance_modal.transactions_view import (
    fetch_tag_options,
    transaction_tag_chips,
)


class BulkActionsMixin(TransactionsPanelState):
    """Bulk curation over the selection: categorize, payee, tags, delete."""

    def _open_bulk_categorize(self, e: ft.ControlEvent) -> None:
        if self._selected_txn_ids:
            self._category_picker.open_for(list(self._selected_txn_ids), e)

    def _open_bulk_payee(self, e: ft.ControlEvent) -> None:
        if self._selected_txn_ids:
            self._merchant_picker.open_for(list(self._selected_txn_ids), e)

    def _open_bulk_recurring(self, _e: ft.ControlEvent) -> None:
        if self._selected_txn_ids and self.page is not None:
            self.page.run_task(self._preview_recurring, list(self._selected_txn_ids))

    # -- tags ------------------------------------------------------------

    def _open_bulk_tag(self, e: ft.ControlEvent) -> None:
        if self._selected_txn_ids:
            self._tag_picker.open_for(list(self._selected_txn_ids), e)

    def _open_bulk_delete(self, _e: ft.ControlEvent) -> None:
        if not self._selected_txn_ids or self.page is None:
            return
        ids = list(self._selected_txn_ids)
        count = len(ids)
        ConfirmDialog(
            self.page,
            title=f"Delete {count} transaction{'s' if count != 1 else ''}?",
            message=(
                f"{count} row{'s' if count != 1 else ''} totalling "
                f"{_usd(self._selected_amount)} will leave the register, "
                "budgets, and projections. Re-importing the same file "
                "will not bring them back."
            ),
            confirm_text="Delete",
            destructive=True,
            on_confirm=lambda: self._delete_transactions(ids),
        ).show()

    async def _delete_transactions(self, transaction_ids: list[int]) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/transactions/delete",
            json={"transaction_ids": transaction_ids},
        )
        deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
        if not deleted:
            ErrorSnackBar("Could not delete those transactions.").launch(self.page)
            return
        SuccessSnackBar(
            f"Deleted {deleted} transaction{'s' if deleted != 1 else ''}."
        ).launch(self.page)
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        await self._load()

    async def _reload_tags(self, api) -> None:
        self._tags = await fetch_tag_options(api)
        self._tag_picker.update_tags(self._tags)

    def _filter_by_tag(self, tag: dict) -> None:
        """A row chip was clicked: narrow the register to that tag."""
        if self.page is None:
            return
        self._tag_filter = tag
        self._render_tag_filter_chip()
        self.page.run_task(self._load)

    def _clear_tag_filter(self, _e: ft.ControlEvent) -> None:
        if self.page is None:
            return
        self._tag_filter = None
        self._render_tag_filter_chip()
        self.page.run_task(self._load)

    def _render_tag_filter_chip(self) -> None:
        """The active-filter chip beside the subtitle - the register never
        silently narrows; whatever is filtering it is on screen with an x."""
        active = self._tag_filter
        self._tag_filter_chip.visible = active is not None
        self._tag_filter_chip.content = (
            transaction_tag_chips(
                [active],
                on_remove=lambda _t: self._clear_tag_filter(None),
                remove_tooltip="Stop filtering by this tag",
            )[0]
            if active is not None
            else None
        )
        if self._tag_filter_chip.page is not None:
            self._tag_filter_chip.update()

    def _remove_tag(self, txn: dict, tag: dict) -> None:
        """The expanded row's chip x - detach one tag from one row."""
        if self.page is None:
            return
        self.page.run_task(self._remove_tag_async, txn, tag)

    async def _remove_tag_async(self, txn: dict, tag: dict) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        await api.delete(f"/api/v1/finance/transactions/{txn['id']}/tags/{tag['id']}")
        await self._load()

    def _pick_category(self, transaction_ids: list[int], category_key: str) -> None:
        """CategoryPickerButton's on_pick contract - a single row's pick
        and a bulk "recategorize the selected rows" pick both land here,
        just with a longer list. Applies immediately (no pending/Save
        staging - see the constructor comment on why)."""
        if not category_key or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_category, transaction_ids, int(category_key))

    def _create_category(self, transaction_ids: list[int], name: str) -> None:
        """CategoryPickerButton's on_create contract: name a category that
        does not exist, then use it on the rows that needed it."""
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._create_and_apply, transaction_ids, name)

    async def _create_and_apply(self, transaction_ids: list[int], name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await create_category(api, name)
        if created is None:
            ErrorSnackBar("Could not create that category.").launch(self.page)
            return
        key, stored = created
        # Straight into the list so the picker has it without a reload,
        # and re-sorted because the picker shows them in order.
        if key not in {k for k, _ in self._categories}:
            self._categories = sorted(
                [*self._categories, (key, stored)], key=lambda c: c[1].casefold()
            )
            self._category_picker.update_categories(self._categories)
        await self._apply_category(transaction_ids, int(key))

    async def _apply_category(
        self, transaction_ids: list[int], category_id: int
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        saved_ids = await apply_category_picks(
            api, [(t, category_id) for t in transaction_ids]
        )
        failed = len(transaction_ids) - len(saved_ids)
        message = (
            f"Recategorized {len(saved_ids)}."
            if not failed
            else f"Recategorized {len(saved_ids)}, {failed} failed."
        )
        (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        await self._load()

    # -- payee assignment ----------------------------------------------------

    async def _reload_merchants(self, api) -> None:
        data = await api.get("/api/v1/finance/merchants", cache_ttl=30)
        items = data.get("items", []) if isinstance(data, dict) else []
        self._merchants = [(str(m["id"]), m["name"]) for m in items]
        self._merchant_picker.update_merchants(self._merchants)

    def _pick_merchant(self, transaction_ids: list[int], merchant_key: str) -> None:
        """MerchantPickerButton's on_pick - an existing payee was chosen."""
        if not merchant_key or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._apply_merchant, transaction_ids, int(merchant_key))

    def _create_merchant(self, transaction_ids: list[int], name: str) -> None:
        """MerchantPickerButton's on_create - a payee named inline."""
        if not name or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._create_and_apply_merchant, transaction_ids, name)

    async def _create_and_apply_merchant(
        self, transaction_ids: list[int], name: str
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await api.post("/api/v1/finance/merchants", json={"name": name})
        if not isinstance(created, dict) or created.get("id") is None:
            ErrorSnackBar(f'Could not create the payee "{name}".').launch(self.page)
            return
        await self._reload_merchants(api)
        await self._apply_merchant(transaction_ids, int(created["id"]))

    async def _apply_merchant(
        self, transaction_ids: list[int], merchant_id: int
    ) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        result = await api.post(
            "/api/v1/finance/transactions/assign-merchant",
            json={"transaction_ids": transaction_ids, "merchant_id": merchant_id},
        )
        if not isinstance(result, dict):
            ErrorSnackBar("Could not set the payee.").launch(self.page)
            return
        updated = result.get("updated", 0)
        SuccessSnackBar(
            f"Payee set on {updated} transaction{'s' if updated != 1 else ''}."
        ).launch(self.page)
        # Only sweep for lookalikes after a SINGLE row: following a bulk
        # assign the user has already said which rows they meant, and
        # re-asking about lookalikes on top of an explicit selection is
        # second-guessing it. The category offer applies either way.
        similar = []
        if len(transaction_ids) == 1:
            data = await api.get(
                f"/api/v1/finance/transactions/{transaction_ids[0]}/similar"
            )
            similar = data.get("items", []) if isinstance(data, dict) else []
        summary = await api.get(
            f"/api/v1/finance/merchants/{merchant_id}/category-summary"
        )
        summary = summary if isinstance(summary, dict) else {}
        self._selected_txn_ids.clear()
        self._selected_amount = 0
        if similar or self._category_offer_worth_making(summary):
            await self._offer_followup(api, merchant_id, similar, summary)
        await self._load()
