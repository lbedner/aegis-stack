"""Staging a category onto a row, and committing the batch."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import flet as ft

from app.components.frontend.controls.snack_bar import ErrorSnackBar, SuccessSnackBar

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
from app.components.frontend.dashboard.modals.finance_modal.curation_shared import (
    apply_category_picks,
    create_category,
)


class CategoryStagingMixin:
    """Nothing here writes a row on its own: picks and suggestions land in

    ``_pending`` and only ``_save_pending`` sends them.
    """

    if TYPE_CHECKING:
        page: ft.Page | None
        update: Callable[[], None]
        _categories: list[dict[str, Any]]
        _category_picker: Any
        _items: list[dict[str, Any]]
        _pending: dict[int, int]
        _progress: Any
        _selected: set[int]
        _suggested: dict[int, Any]
        _total: int

        def _refresh_category_cell(self, *args: Any, **kwargs: Any) -> Any: ...
        def _render_table(self, *args: Any, **kwargs: Any) -> Any: ...

    def _pick_category(self, transaction_ids: list[int], category_key: str) -> None:
        """CategoryPickerButton's on_pick contract - a single row's pick
        and a bulk "categorize the selected rows" pick are the same call,
        just with a longer list (see pickers.py's own docstring).
        Stages the pick(s) - does not save."""
        if not category_key:
            return
        category_id = int(category_key)
        for transaction_id in transaction_ids:
            self._pending[transaction_id] = category_id
            self._suggested.pop(transaction_id, None)
            self._refresh_category_cell(transaction_id)

    def _create_category(self, transaction_ids: list[int], name: str) -> None:
        """Name a category, then STAGE it on the rows - this panel saves
        on its own Save button, and creating one must not quietly become
        the exception that writes immediately."""
        if not name.strip() or not transaction_ids or self.page is None:
            return
        self.page.run_task(self._create_and_stage, transaction_ids, name)

    async def _create_and_stage(self, transaction_ids: list[int], name: str) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        created = await create_category(api, name)
        if created is None:
            ErrorSnackBar("Could not create that category.").launch(self.page)
            return
        key, stored = created
        if key not in {k for k, _ in self._categories}:
            self._categories = sorted(
                [*self._categories, (key, stored)], key=lambda c: c[1].casefold()
            )
            self._category_picker.update_categories(self._categories)
        self._pick_category(transaction_ids, key)
        self.page.update()

    def _clear_pending(self, transaction_id: int) -> None:
        self._pending.pop(transaction_id, None)
        self._refresh_category_cell(transaction_id)

    def _accept_suggestion(self, transaction_id: int) -> None:
        suggestion = self._suggested.pop(transaction_id, None)
        if suggestion is not None:
            self._pending[transaction_id] = suggestion[0]
        self._refresh_category_cell(transaction_id)

    def _reject_suggestion(self, transaction_id: int) -> None:
        self._suggested.pop(transaction_id, None)
        self._refresh_category_cell(transaction_id)

    async def _auto_categorize(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        self._progress.visible = True
        if self.page:
            self.update()

        scope = set(self._selected)  # snapshot - cleared below before the render
        api = get_session_state(self.page).api_client
        body = {"transaction_ids": list(scope)} if scope else {}
        result = await api.post(
            "/api/v1/finance/transactions/auto-categorize", json=body
        )
        self._progress.visible = False
        if self.page:
            self.update()
        suggestions = result.get("items", []) if isinstance(result, dict) else []
        added = 0
        for s in suggestions:
            txn_id = s.get("transaction_id")
            # Don't clobber a row the user already picked or already has
            # an unreviewed suggestion on.
            if txn_id is None or txn_id in self._pending or txn_id in self._suggested:
                continue
            self._suggested[txn_id] = (s["category_id"], s.get("category_name") or "")
            added += 1
        scoped_note = f" from {len(scope):,} selected" if scope else ""
        SuccessSnackBar(
            f"{added} suggestion{'s' if added != 1 else ''} ready to review"
            f"{scoped_note}."
            if added
            else "No new suggestions - nothing had a clear category precedent yet."
        ).launch(self.page)
        self._selected.clear()
        # A real rebuild here on purpose (unlike a single accept/reject):
        # this is what re-sorts newly-suggested rows to the top, the
        # whole point of clicking this button being able to review what
        # it proposed without hunting for it in 900 date-sorted rows.
        # Tried skipping this for speed (in-place per-cell updates,
        # keeping rows in place) - lost the grouping, which mattered
        # more than the speed here. Reverted.
        self._render_table()

    async def _save_pending(self) -> None:
        if not self._pending:
            return
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        to_save = list(self._pending.items())
        saved_ids = await apply_category_picks(api, to_save)
        failed = len(to_save) - len(saved_ids)
        message = (
            f"Saved {len(saved_ids)}."
            if not failed
            else f"Saved {len(saved_ids)}, {failed} failed."
        )
        (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)

        # A saved row disappears immediately - tried leaving it visible
        # with a "Saved" confirmation to skip the rebuild below entirely,
        # but that's not what was wanted: hitting Save should remove the
        # row, not leave it lingering until the next reload. Reverted.
        #
        # Still no re-``GET /uncategorized`` though - the POST results
        # above already say exactly which rows just left the backlog, so
        # splicing locally and rebuilding once (no network round trip)
        # is the honest middle ground: correct behavior, still cheaper
        # than the original refetch-then-rebuild.
        saved = set(saved_ids)
        for transaction_id, _ in to_save:
            self._pending.pop(transaction_id, None)
        if saved:
            self._items = [t for t in self._items if t["id"] not in saved]
            self._selected -= saved
            self._total = max(self._total - len(saved), 0)
        self._render_table()
