"""The match-a-payment and pause dialogs.

One mixin of ``RecurringTab`` - state contract in ``base``.
"""

from __future__ import annotations

from datetime import date

import flet as ft

from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormTextField,
)
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_recurring_tab.base import (
    RecurringTabState,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.shared import (
    _RECURRING_URL,
    _usd,
    needs_review,
    pause_label,
    pause_options,
)
from app.components.frontend.dashboard.modals.modal_sections import DateRangeChips
from app.components.frontend.theme import AegisTheme as Theme


class StreamDialogsMixin(RecurringTabState):
    """The match-a-payment and pause dialogs."""

    async def _open_review_queue(self) -> None:
        """Walk every passed bill that HAS likely payments, one dialog
        after another.

        One batch call answers the whole session: the client sends the
        bills it considers past due (needs_review, soonest-due first),
        the server returns each one's shortlist, and bills with nothing
        to offer never enter the queue - so "1 of 4" counts dialogs the
        user will actually see. Each step is the ordinary match dialog
        with its position in the title and a Skip.
        """
        from app.components.frontend.state.session_state import get_session_state

        today_iso = date.today().isoformat()
        passed = sorted(
            (s for s in self._items if needs_review(s, today_iso)),
            key=lambda s: s.get("next_expected_date") or "",
        )
        if not passed:
            SuccessSnackBar("Nothing has passed its due date.").launch(self.page)
            return
        api = get_session_state(self.page).api_client
        ids = ",".join(str(s.get("id")) for s in passed)
        data = await api.get(f"{_RECURRING_URL}/review-queue?ids={ids}")
        if not isinstance(data, dict):
            ErrorSnackBar(
                api.last_error or "Could not load the review queue."
            ).launch(self.page)
            return
        by_id = {s.get("id"): s for s in passed}
        queue = [
            (by_id[entry["stream_id"]], entry["candidates"])
            for entry in data.get("items", [])
            if entry.get("stream_id") in by_id and entry.get("candidates")
        ]
        if not queue:
            SuccessSnackBar(
                f"No likely payments found for the {len(passed)} passed "
                "bill(s) - they may simply not be imported yet."
            ).launch(self.page)
            return
        stream, items = queue[0]
        await self._open_match_dialog(stream, queue=queue, index=0, items=items)

    async def _advance_queue(
        self, queue: list[tuple[dict, list[dict]]], index: int
    ) -> None:
        if index + 1 < len(queue):
            stream, items = queue[index + 1]
            await self._open_match_dialog(
                stream, queue=queue, index=index + 1, items=items
            )
        else:
            SuccessSnackBar("Reviewed every overdue bill.").launch(self.page)

    async def _open_match_dialog(
        self,
        stream: dict,
        *,
        queue: list[tuple[dict, list[dict]]] | None = None,
        index: int = 0,
        items: list[dict] | None = None,
    ) -> None:
        """Pick the transaction that paid this bill.

        Candidates come pre-shortlisted (same direction, unclaimed,
        amount in the bill's neighborhood, newest first) but the CHOICE
        is the user's - this exists precisely because the automatic
        matcher was wrong to find nothing, so a second automatic guess
        would repeat the mistake with confidence.

        With a ``queue``, this is one step of a review session: the
        title carries the position, Skip moves on, and a pick advances
        instead of just closing.
        """
        from app.components.frontend.state.session_state import get_session_state

        api = get_session_state(self.page).api_client
        if items is None:
            # Single-bill path (from the row): fetch this bill's
            # shortlist. Review sessions arrive with candidates already
            # loaded by the batch endpoint, which also guarantees they
            # are non-empty - a bill with nothing to offer never became
            # a step at all.
            data = await api.get(
                f"{_RECURRING_URL}/{stream.get('id')}/match-candidates"
            )
            if not isinstance(data, dict):
                # A failed fetch is not "no matches" - saying so sent a
                # real payment on a hunt for a bug that was actually a
                # 500 here.
                ErrorSnackBar(
                    api.last_error or "Could not load match candidates."
                ).launch(self.page)
                return
            items = data.get("items", [])
        dialog: StyledAlertDialog | None = None

        async def _cancel() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _pick(txn: dict) -> None:
            await _cancel()
            result = await api.post(
                f"{_RECURRING_URL}/{stream.get('id')}/attach",
                json={"transaction_id": txn.get("id")},
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not match.").launch(self.page)
                return
            SuccessSnackBar(
                f"Matched. {stream.get('name')} is paid; next expected "
                f"{result.get('next_expected_date') or 'never (one-time)'}."
            ).launch(self.page)
            await self._load()
            if queue is not None:
                await self._advance_queue(queue, index)

        async def _skip() -> None:
            await _cancel()
            if queue is not None:
                await self._advance_queue(queue, index)

        if not items:
            rows: list[ft.Control] = [
                SecondaryText(
                    "No unclaimed transactions look like this bill. The "
                    "payment may not be imported yet, or its amount is "
                    "far from the bill's figure."
                )
            ]
        else:
            rows = [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Column(
                                [
                                    TableNameText(
                                        t.get("merchant") or t.get("name") or ""
                                    ),
                                    SecondaryText(
                                        f"{t.get('date')} · "
                                        f"{t.get('account_name') or ''}",
                                        size=Theme.Typography.BODY_SMALL,
                                    ),
                                ],
                                spacing=0,
                                tight=True,
                            ),
                            expand=True,
                        ),
                        NumericText(
                            _usd(t.get("amount", 0)),
                            size=Theme.Typography.BODY_SMALL,
                        ),
                        PulseButton(
                            on_click_callable=(lambda txn=t: _pick(txn)),
                            text="This one",
                            variant="teal",
                            compact=True,
                        ),
                    ],
                    spacing=Theme.Spacing.MD,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                for t in items
            ]

        position = f" ({index + 1} of {len(queue)})" if queue is not None else ""
        actions: list[ft.Control] = [
            PulseButton(
                on_click_callable=_cancel,
                text="Cancel" if queue is None else "Stop reviewing",
                variant="muted",
                compact=True,
            )
        ]
        if queue is not None:
            actions.append(
                PulseButton(
                    on_click_callable=_skip,
                    text="Skip",
                    variant="teal",
                    compact=True,
                )
            )
        dialog = StyledAlertDialog(
            title=f"Which payment was {stream.get('name')}?{position}",
            body=ft.Column(
                rows,
                spacing=Theme.Spacing.SM,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                height=min(60 * max(len(rows), 1) + 20, 420),
            ),
            actions=actions,
            width=520,
        )
        self.page.open(dialog)

    def _open_pause_dialog(self, stream_ids: list[int]) -> None:
        """Until when, and optionally why. One dialog for a single row
        (the edit dialog's Pause) and a checked set (the bulk action).

        The why goes to ``metadata_`` server-side and comes back on the
        row's Paused tooltip - the note future-you reads after forgetting
        why an investment went quiet ("waiting until the pool is paid
        off"). Optional on purpose; a required field would get junk.
        """
        from app.services.finance.constants import PAUSE_INDEFINITE, add_months

        today = date.today()
        until = FormDateField(
            label="Paused until",
            value=pause_options(today)[2][1].isoformat(),  # 3 months
            width=200,
        )
        note = FormTextField(
            label="Why? (optional, shown on the row)",
            hint="e.g. pausing investments until the pool is paid off",
            width=360,
        )
        state = {"indefinite": False}

        def _on_pick(months: int) -> None:
            # 0 is the "No end date" chip: the date field hides rather
            # than displaying the sentinel year, which is an
            # implementation detail nobody should read.
            state["indefinite"] = months == 0
            until.visible = months != 0
            if months:
                until.value = add_months(today, months).isoformat()
            if until.page:
                until.update()

        # The SAME chips control every range picker in the product uses,
        # so the selected pick carries the standard teal pill treatment
        # instead of four identical muted buttons with no state.
        quick_row = DateRangeChips(
            options=[
                ("1 month", 1),
                ("2 months", 2),
                ("3 months", 3),
                ("6 months", 6),
                ("No end date", 0),
            ],
            selected_days=3,
            on_change=_on_pick,
        )
        dialog: StyledAlertDialog | None = None

        async def _cancel() -> None:
            if dialog is not None:
                dialog.open = False
            self.page.update()

        async def _apply() -> None:
            from app.components.frontend.state.session_state import (
                get_session_state,
            )

            if state["indefinite"]:
                when = PAUSE_INDEFINITE
            else:
                raw = (until.value or "").strip()
                try:
                    when = date.fromisoformat(raw)
                except ValueError:
                    ErrorSnackBar("Pick a date to pause until.").launch(self.page)
                    return
                if when <= today:
                    ErrorSnackBar("The pause needs a future date.").launch(self.page)
                    return
            await _cancel()
            api = get_session_state(self.page).api_client
            body: dict[str, str] = {"until": when.isoformat()}
            note_text = (note.value or "").strip()
            if note_text:
                body["note"] = note_text
            done = 0
            for stream_id in stream_ids:
                await api.post(f"{_RECURRING_URL}/{stream_id}/pause", json=body)
                if not api.last_error:
                    done += 1
            failed = len(stream_ids) - done
            message = (
                f"Paused {done} {pause_label(when.isoformat())}."
                if not failed
                else f"Paused {done}, {failed} failed."
            )
            (ErrorSnackBar if failed else SuccessSnackBar)(message).launch(self.page)
            self._selected.clear()
            self._update_selection()
            await self._load()

        count = len(stream_ids)
        dialog = StyledAlertDialog(
            title=("Pause this bill" if count == 1 else f"Pause {count} bills"),
            body=ft.Column(
                [
                    quick_row,
                    until,
                    note,
                    SecondaryText(
                        "Out of the forecast, the Bills total and every "
                        "nag until then - back on its own the day the "
                        "date passes.",
                        size=Theme.Typography.BODY_SMALL,
                    ),
                ],
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
                    on_click_callable=_apply,
                    text="Pause",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=420,
        )
        self.page.open(dialog)
