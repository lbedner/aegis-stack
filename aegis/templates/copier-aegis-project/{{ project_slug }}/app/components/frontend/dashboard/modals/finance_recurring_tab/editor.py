"""The add/edit bill dialogs.

One mixin of ``RecurringTab`` - state contract in ``base``.
"""

from __future__ import annotations

import flet as ft

from app.components.frontend.controls.buttons import (
    ConfirmDialog,
    PulseButton,
)
from app.components.frontend.controls.dialog import StyledAlertDialog
from app.components.frontend.controls.form_fields import (
    FormDateField,
    FormDropdown,
    FormTextField,
)
from app.components.frontend.controls.pickers import CategoryPickerField
from app.components.frontend.controls.snack_bar import (
    ErrorSnackBar,
    SuccessSnackBar,
)
from app.components.frontend.dashboard.modals.finance_modal import (
    BILL_FREQUENCY_OPTIONS,
)
from app.components.frontend.dashboard.modals.finance_modal.formatting import (
    _parse_dollars,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.base import (
    RecurringTabState,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.shared import (
    _RECURRING_URL,
    pause_label,
    stream_is_paused,
)
from app.components.frontend.theme import AegisTheme as Theme


class StreamEditorMixin(RecurringTabState):
    """The add/edit bill dialogs."""

    # -- add dialog --------------------------------------------------------

    async def _open_add(self) -> None:
        """Declare a bill or income by hand (name, kind, amount, cadence, due)."""
        form = {"name": "", "amount": "", "due": ""}
        name = FormTextField(
            label="Name",
            on_change=lambda e: form.__setitem__(
                "name", (getattr(e.control, "value", "") or "").strip()
            ),
            width=360,
        )
        kind_dd = FormDropdown(
            label="Kind",
            options=[("outflow", "Bill"), ("inflow", "Income")],
            value="outflow",
            width=360,
        )
        amount = FormTextField(
            label="Amount ($)",
            on_change=lambda e: form.__setitem__(
                "amount", getattr(e.control, "value", "") or ""
            ),
            width=360,
        )
        frequency_dd = FormDropdown(
            label="Repeats",
            options=list(BILL_FREQUENCY_OPTIONS.items()),
            value="monthly",
            width=360,
        )
        due = FormDateField(
            label="Next due date",
            on_change=lambda iso: form.__setitem__("due", iso),
            width=360,
        )
        # Offered at creation, not just afterwards: a bill saved without
        # one is invisible to Projected until somebody notices.
        add_account_dd = FormDropdown(
            label="Account",
            options=[("", "No account"), *self._accounts],
            value="",
            width=360,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _add() -> None:
            if not form["name"]:
                ErrorSnackBar("Name is required.").launch(self.page)
                return
            cents = _parse_dollars(form["amount"])
            if cents <= 0:
                ErrorSnackBar("Amount must be more than $0.").launch(self.page)
                return
            from datetime import date as date_cls

            try:
                due_date = date_cls.fromisoformat(form["due"])
            except ValueError:
                # Only reachable when nothing was picked - the calendar
                # cannot hand back a malformed date.
                ErrorSnackBar("Pick a next due date.").launch(self.page)
                return
            dialog.open = False
            self.page.update()

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.post(
                _RECURRING_URL,
                json={
                    "name": form["name"],
                    "direction": kind_dd.value or "outflow",
                    "frequency": frequency_dd.value or "monthly",
                    "expected_amount": cents,
                    "next_expected_date": due_date.isoformat(),
                    **(
                        {"account_id": int(add_account_dd.value)}
                        if add_account_dd.value
                        else {}
                    ),
                },
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
                return
            SuccessSnackBar(f"{form['name']} added.").launch(self.page)
            await self._load()

        dialog = StyledAlertDialog(
            title="Add a bill or income",
            body=ft.Column(
                [name, kind_dd, amount, frequency_dd, due, add_account_dd],
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
                    on_click_callable=_add,
                    text="Add",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=400,
        )
        self.page.open(dialog)

    async def _open_edit(self, stream: dict) -> None:
        """Edit a stream's declared facts. Only changed fields are sent, so
        an untouched form is a no-op and a detected stream's fields (like a
        cadence outside the manual-entry set) survive unedited."""
        current_amount = (
            stream.get("expected_amount") or stream.get("average_amount") or 0
        )
        current_freq = stream.get("frequency") or "monthly"
        current_due = stream.get("next_expected_date") or ""
        name = FormTextField(
            label="Name",
            value=stream.get("name") or "",
        )
        # The detector produces cadences (bimonthly, semi-annual) the
        # manual-entry set doesn't offer; the current one is always a
        # choice so opening the dropdown never lies about the stream.
        freq_options = list(BILL_FREQUENCY_OPTIONS.items())
        if current_freq not in BILL_FREQUENCY_OPTIONS:
            freq_options.append((current_freq, current_freq.replace("_", " ").title()))
        frequency_dd = FormDropdown(
            label="Repeats",
            options=freq_options,
            value=current_freq,
        )
        amount = FormTextField(
            label="Amount ($)",
            value=f"{current_amount / 100:.2f}" if current_amount else "",
        )
        due = FormDateField(
            label="Next due date",
            value=current_due,
        )
        # The bill's OWN category. Blank means "keep inferring it from the
        # transactions", which is what every bill does until someone
        # states otherwise (FinanceService.stream_category_names).
        current_category = str(stream.get("category_id") or "")
        category_dd = CategoryPickerField(
            categories=self._categories,
            value=current_category,
        )
        current_account = str(stream.get("account_id") or "")
        account_dd = FormDropdown(
            label="Account",
            options=[("", "No account"), *self._accounts],
            value=current_account,
        )

        async def _cancel() -> None:
            dialog.open = False
            self.page.update()

        async def _toggle_mute() -> None:
            dialog.open = False
            self.page.update()

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            verb = "unmute" if stream.get("is_muted") else "mute"
            result = await api.post(f"{_RECURRING_URL}/{stream.get('id')}/{verb}")
            if result is None:
                ErrorSnackBar(api.last_error or f"Could not {verb}.").launch(self.page)
                return
            SuccessSnackBar(f"{stream.get('name')} {verb}d.").launch(self.page)
            await self._load()

        async def _confirm_delete() -> None:
            dialog.open = False
            self.page.update()

            async def _do_delete() -> None:
                from app.components.frontend.state.session_state import (
                    get_session_state,
                )

                api = get_session_state(self.page).api_client
                await api.delete(f"{_RECURRING_URL}/{stream.get('id')}")
                SuccessSnackBar(f"{stream.get('name')} deleted.").launch(self.page)
                await self._load()

            detected = stream.get("source") not in (None, "user")
            ConfirmDialog(
                page=self.page,
                title="Delete bill or income",
                message=(
                    f'Delete "{stream.get("name", "")}"? Its transactions are '
                    "kept; only this recurring entry goes away."
                    + (
                        " If the pattern keeps appearing in imports, it can "
                        "be detected again - it will come back muted."
                        if detected
                        else ""
                    )
                ),
                confirm_text="Delete",
                destructive=True,
                on_confirm=_do_delete,
            ).show()

        async def _save() -> None:
            payload: dict = {}
            new_name = (name.value or "").strip()
            if not new_name:
                ErrorSnackBar("Name is required.").launch(self.page)
                return
            if new_name != (stream.get("name") or ""):
                payload["name"] = new_name
            cents = _parse_dollars(amount.value or "")
            if cents <= 0:
                ErrorSnackBar("Amount must be more than $0.").launch(self.page)
                return
            if cents != current_amount:
                payload["expected_amount"] = cents
            if (frequency_dd.value or current_freq) != current_freq:
                payload["frequency"] = frequency_dd.value
            # Always ISO - FormDateField only ever holds what the calendar
            # produced, so there is nothing left to validate here.
            due_text = due.value
            if due_text and due_text != current_due:
                payload["next_expected_date"] = due_text
            picked_category = category_dd.value or ""
            if picked_category != current_category and picked_category:
                payload["category_id"] = int(picked_category)
            picked_account = account_dd.value or ""
            if picked_account != current_account and picked_account:
                payload["account_id"] = int(picked_account)
            dialog.open = False
            self.page.update()
            if not payload:
                return

            from app.components.frontend.state.session_state import get_session_state

            api = get_session_state(self.page).api_client
            result = await api.patch(
                f"{_RECURRING_URL}/{stream.get('id')}", json=payload
            )
            if result is None:
                ErrorSnackBar(api.last_error or "Could not save.").launch(self.page)
                return
            SuccessSnackBar(f"{new_name} updated.").launch(self.page)
            await self._load()

        async def _toggle_pause() -> None:
            dialog.open = False
            self.page.update()
            if stream_is_paused(stream):
                from app.components.frontend.state.session_state import (
                    get_session_state,
                )

                api = get_session_state(self.page).api_client
                await api.post(f"{_RECURRING_URL}/{stream.get('id')}/resume")
                if api.last_error:
                    ErrorSnackBar(api.last_error).launch(self.page)
                    return
                SuccessSnackBar(f"{stream.get('name')} resumed.").launch(self.page)
                await self._load()
                return
            self._open_pause_dialog([int(stream.get("id"))])

        async def _open_match() -> None:
            dialog.open = False
            self.page.update()
            await self._open_match_dialog(stream)

        match_button = PulseButton(
            on_click_callable=_open_match,
            text="Match...",
            variant="muted",
            compact=True,
        )
        match_button.tooltip = (
            "Point this bill at the transaction that paid it - consumes "
            "the occurrence and teaches the matcher for next month"
        )
        pause_button = PulseButton(
            on_click_callable=_toggle_pause,
            text="Resume" if stream_is_paused(stream) else "Pause...",
            variant="muted",
            compact=True,
        )
        pause_button.tooltip = (
            f"Paused {pause_label(stream.get('paused_until'))} - end it early"
            if stream_is_paused(stream)
            else "Skip this for a while: out of the forecast and totals "
            "until a date you pick, back on its own after"
        )
        mute_button = PulseButton(
            on_click_callable=_toggle_mute,
            text="Unmute" if stream.get("is_muted") else "Mute",
            variant="muted",
            compact=True,
        )
        mute_button.tooltip = (
            "Resume insights about this stream"
            if stream.get("is_muted")
            else "Stop insights about this stream"
        )
        delete_button = PulseButton(
            on_click_callable=_confirm_delete,
            text="Delete",
            variant="stop",
            compact=True,
        )
        delete_button.tooltip = "Remove this entry. Transactions are kept."
        dialog = StyledAlertDialog(
            title="Edit bill or income",
            # No width pins on the fields: the house form controls
            # stretch by design, and the STRETCH alignment is what lets
            # the dialog's width govern - six hardcoded width=360 pins
            # here are why widening the dialog once just grew margin.
            body=ft.Column(
                [name, amount, frequency_dd, due, category_dd, account_dd],
                spacing=Theme.Spacing.MD,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            # One row, dialog widened to hold it: Delete and the stream
            # verbs (Mute/Pause/Match) sit apart on the left - they act
            # on the bill itself, not the form - Cancel/Save on the
            # right. 400px fit four buttons; six need the width.
            actions=[
                delete_button,
                mute_button,
                pause_button,
                match_button,
                ft.Container(expand=True),
                PulseButton(
                    on_click_callable=_cancel,
                    text="Cancel",
                    variant="muted",
                    compact=True,
                ),
                PulseButton(
                    on_click_callable=_save,
                    text="Save",
                    variant="teal",
                    compact=True,
                ),
            ],
            width=560,
        )
        self.page.open(dialog)
