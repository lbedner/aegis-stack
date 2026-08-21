"""Bulk verbs over the selection: categorize, pause, mute, delete, rescan.

One mixin of ``RecurringTab`` - state contract in ``base``.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls.buttons import ConfirmDialog
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.base import (
    RecurringTabState,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.shared import (
    _RECURRING_URL,
)


class StreamActionsMixin(RecurringTabState):
    """Bulk verbs over the selection: categorize, pause, mute, delete, rescan."""

    def _open_bulk_categorize(self, e: ft.ControlEvent) -> None:
        if self._selected:
            self._category_picker.open_for(list(self._selected), e)

    def _pick_category(self, stream_ids: list[int], category_key: str) -> None:
        """CategoryPickerButton's on_pick contract. The bills only - their
        transactions keep the categories they have, because a bill's
        category is otherwise inferred from them and a cascade would
        overwrite corrections made by hand."""
        if not category_key or not stream_ids or self.page is None:
            return
        self.page.run_task(self._apply_category, stream_ids, int(category_key))

    async def _apply_category(self, stream_ids: list[int], category_id: int) -> None:
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            result = await api.post(
                f"{_RECURRING_URL}/categorize",
                json={"stream_ids": stream_ids, "category_id": category_id},
            )
            if not isinstance(result, dict):
                ErrorSnackBar("Could not set the category.").launch(self.page)
                return
            updated = result.get("updated", 0)
            SuccessSnackBar(
                f"Category set on {updated} bill{'s' if updated != 1 else ''}."
            ).launch(self.page)
            self._selected.clear()
            self._update_selection()
            await self._load()
        finally:
            self._set_busy(False)

    async def _rescan(self) -> None:
        """Re-run detection so payees named since the last pass attach to
        their bills (and their icons follow)."""
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            result = await api.post(f"{_RECURRING_URL}/rescan")
            if not isinstance(result, dict):
                ErrorSnackBar(api.last_error or "Re-scan failed.").launch(self.page)
                return
            detected = result.get("detected", 0)
            pruned = result.get("pruned", 0)
            SuccessSnackBar(
                f"Re-scanned: {detected} bill{'s' if detected != 1 else ''}"
                + (f", {pruned} retired" if pruned else "")
                + "."
            ).launch(self.page)
            await self._load()
        finally:
            self._set_busy(False)

    async def _bulk_pause(self) -> None:
        if self._selected:
            self._open_pause_dialog(sorted(self._selected))

    async def _bulk_mute(self) -> None:
        """Mute is reversible (Unmute stays reachable on Detected), so it
        applies straight away - no confirm for something a click undoes."""
        await self._bulk_apply("mute")

    async def _bulk_delete(self) -> None:
        """Delete asks first: it drops rows out of Bills & Income, and for
        a hand-entered bill there is nothing to re-detect it from."""
        count = len(self._selected)
        if not count:
            return

        async def _confirm() -> None:
            await self._bulk_apply("delete")

        ConfirmDialog(
            page=self.page,
            title="Delete these?",
            message=(
                f"Remove {count} row{'s' if count != 1 else ''} from Bills & "
                "Income? Detected ones are muted so detection cannot bring "
                "them straight back; anything you added by hand is gone for "
                "good."
            ),
            confirm_text=f"Delete {count}",
            destructive=True,
            on_confirm=_confirm,
        ).show()

    async def _bulk_apply(self, verb: str) -> None:
        """One request per stream - the recurring API is per-id, and a
        failure on one row should not abandon the rest, so results are
        tallied rather than raised."""
        from app.components.frontend.state.session_state import get_session_state

        ids = sorted(self._selected)
        if not ids:
            return
        api = get_session_state(self.page).api_client
        self._set_busy(True)
        try:
            done = 0
            for stream_id in ids:
                if verb == "delete":
                    await api.delete(f"{_RECURRING_URL}/{stream_id}")
                else:
                    await api.post(f"{_RECURRING_URL}/{stream_id}/{verb}")
                # APIClient returns None on failure and never raises; delete
                # answers 204 (no body), so "not None" is the wrong test
                # there - last_error is the honest signal for both.
                if not api.last_error:
                    done += 1
            failed = len(ids) - done
            word = "Deleted" if verb == "delete" else "Muted"
            message = (
                f"{word} {done}." if not failed else f"{word} {done}, {failed} failed."
            )
            (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)
            self._selected.clear()
            self._update_selection()
            await self._load()
        finally:
            self._set_busy(False)

    def _action(self, stream_id: int, verb: str):
        async def _do() -> None:
            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.post(f"{_RECURRING_URL}/{stream_id}/{verb}")
            if result is None:
                ErrorSnackBar(api.last_error or f"Could not {verb}.").launch(self.page)
                return
            await self._load()

        return _do

    def _set_busy(self, busy: bool) -> None:
        self._progress.visible = busy
        if self._progress.page:
            self._progress.update()
