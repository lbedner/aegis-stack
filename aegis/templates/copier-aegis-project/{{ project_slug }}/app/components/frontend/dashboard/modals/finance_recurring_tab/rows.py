"""The table: filtering, columns, one row per stream.

One mixin of ``RecurringTab`` - state contract in ``base``.
"""

from __future__ import annotations

from datetime import (
    date,
    timedelta,
)

import flet as ft

from app.components.frontend.controls import (
    NumericText,
    SecondaryText,
)
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.data_table import (
    DataTable,
    DataTableColumn,
)
from app.components.frontend.controls.provider_icon import ProviderIcon
from app.components.frontend.controls.table import TableNameText
from app.components.frontend.dashboard.modals.finance_modal import (
    _category_leaf,
    _frequency_label,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.base import (
    RecurringTabState,
)
from app.components.frontend.dashboard.modals.finance_recurring_tab.shared import (
    _COLUMNS,
    _NEXT_DUE_COLUMN,
    _NEXT_DUE_SORT_DESC,
    _is_curated,
    _status_key,
    _usd,
    pause_label,
    stream_is_paused,
)
from app.components.frontend.dashboard.modals.modal_sections import (
    date_cell,
    row_matches,
    status_dot,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_date

# staleness (backend, stream_staleness) -> (label, color, tooltip-body).
# Mirrors the exact recency signal _missed_recurring already uses to
# decide whether a bill is genuinely overdue vs. a zombie out of imported
# history - this just surfaces it per-row instead of a hidden insight.
_HEALTH_STYLE: dict[str, tuple[str, str, str]] = {
    "fresh": (
        "Active",
        Theme.Colors.SUCCESS,
        "Matched recently and on cadence.",
    ),
    "overdue": (
        "Overdue",
        Theme.Colors.WARNING,
        "Past due beyond the grace window - hasn't arrived yet.",
    ),
    "stale": (
        "Stale",
        Theme.Colors.ERROR,
        "Last matched before the lookback window - probably not a live bill anymore.",
    ),
}


class RowsMixin(RecurringTabState):
    """The table: filtering, columns, one row per stream."""

    def _table(self, streams: list[dict]) -> ft.Control:
        has_actions = any(
            s.get("direction") == "outflow" and not _is_curated(s) for s in streams
        )
        # Status only when the rows disagree: Bills is every-row "Good" and
        # Income every-row "Good", so the column says nothing the sub-tab
        # has not. Detected mixes Detected with Muted, and there it earns
        # its width.
        has_status = len({_status_key(s) for s in streams}) > 1
        columns = list(_COLUMNS)
        if has_status:
            columns.append(DataTableColumn("Status", width=110))
        if has_actions:
            columns.append(DataTableColumn("Actions", width=110, hideable=False))
        rows = [
            self._row(stream, with_status=has_status, with_actions=has_actions)
            for stream in streams
        ]

        # Row click opens the edit dialog (indices are pre-sort originals).
        # The in-row buttons win their own taps, so Confirm still works.
        def _edit_row(index: int) -> None:
            if self.page:
                self.page.run_task(self._open_edit, streams[index])

        def _on_selection(indices: set[int], _streams: list = streams) -> None:
            self._selected = {
                _streams[i]["id"]
                for i in indices
                if i < len(_streams) and _streams[i].get("id") is not None
            }
            self._update_selection()

        # A selection survives a re-render (a search keystroke, a sub-tab
        # switch back) for any row still on screen - same id-based seeding
        # UncategorizedPanel uses.
        selected_indices = {
            i for i, s in enumerate(streams) if s.get("id") in self._selected
        }

        return ft.Container(
            content=DataTable(
                columns=columns,
                rows=rows,
                row_padding=6,
                show_header_border=True,
                show_row_borders=True,
                on_row_click=_edit_row,
                selectable=True,
                selected_indices=selected_indices,
                on_selection_change=_on_selection,
                initial_sort=_NEXT_DUE_COLUMN,
                initial_sort_desc=_NEXT_DUE_SORT_DESC,
                column_picker=True,
                empty_message="None yet. Add one, or import a file.",
                # Virtualized + fills the tab: detection over a deep import
                # leaves hundreds of streams.
                expand=True,
            ),
            padding=ft.padding.only(top=Theme.Spacing.SM),
            expand=True,
        )

    def _row(
        self,
        stream: dict,
        *,
        with_status: bool = False,
        with_actions: bool = False,
    ) -> list:
        amount = stream.get("expected_amount") or stream.get("average_amount")
        cadence = _frequency_label(stream.get("frequency", ""))
        if stream.get("amount_is_variable"):
            cadence = f"{cadence} · varies"

        # Three states, health-style: green Good (being watched), amber
        # Detected (awaiting your call), gray Muted. WHY a stream is good
        # (income, hand-entered, confirmed, promoted from your categories)
        # lives in the tooltip instead of splintering the label.
        if stream.get("is_muted"):
            status_control = status_dot(
                "Muted",
                Theme.Colors.TEXT_SECONDARY,
                "Silenced. This stream raises no insights until unmuted.",
            )
        elif stream_is_paused(stream):
            until = stream.get("paused_until")
            note = stream.get("pause_note")
            status_control = status_dot(
                "Paused",
                Theme.Colors.TEXT_SECONDARY,
                f"Paused {pause_label(until)}."
                + (f" Why: {note}" if note else "")
                + " Out of the forecast, the Bills total and every nag "
                "until then; back on its own the day the date passes.",
            )
        elif stream.get("is_payment"):
            # A transfer, but a payment FIRST: it drains cash on a rhythm
            # the forecast charges once confirmed, while staying out of
            # the Bills total (the card's swipes already counted there).
            status_control = status_dot(
                "Payment",
                Theme.Colors.ACCENT,
                "A card or loan payment. Confirm it (and pin the amount) "
                "and the cash forecast will charge it; it never counts in "
                "the Bills total, because the card's own charges already "
                "did.",
            )
        elif stream.get("direction") == "inflow":
            # Income needs no curation: the missed-payment rule chases
            # every income stream at any cadence, so "Detected" would be
            # a question with nothing riding on the answer.
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "Income is always tracked. A missed deposit is flagged "
                "at any cadence, no confirmation needed.",
            )
        elif stream.get("source") == "user":
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "You added this by hand. It is treated as a real "
                "commitment: missed payments are flagged.",
            )
        elif stream.get("is_user_confirmed"):
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "You confirmed this is real. Missed payments are flagged "
                "and it counts toward the monthly total.",
            )
        elif stream.get("is_subscription"):
            status_control = status_dot(
                "Good",
                Theme.Colors.SUCCESS,
                "Marked as a bill from your own categorization (or a "
                "recognized subscription). Counts toward the monthly total.",
            )
        else:
            status_control = status_dot(
                "Detected",
                Theme.Colors.WARNING,
                "The cadence detector thinks this repeats and may be a "
                "bill. Confirm to treat it as one, or Mute to dismiss.",
            )

        actions: list[ft.Control] = []
        stream_id = stream.get("id")
        # Confirm is Detected's verb: it promotes an unapproved outflow into
        # a chased commitment. Income is chased unconditionally, and a
        # curated bill is already vouched for - on both, a Confirm button
        # would be a no-op wearing a label.
        if stream.get("direction") == "outflow" and not _is_curated(stream):
            confirm = PulseButton(
                on_click_callable=self._action(stream_id, "confirm"),
                text="Confirm",
                compact=True,
            )
            confirm.tooltip = "Mark as a real bill; missed payments will be flagged"
            actions.append(confirm)
        name = stream.get("name") or ""
        # expand=True on the TEXT, not tight=True on the Row - same
        # truncation recipe _pending_cell already uses below: without it
        # the Row sizes to its children's full natural width (icon + the
        # WHOLE untruncated name) instead of the column's actual width,
        # and a long detected-transaction name (raw bank descriptors run
        # long) paints straight past the Name column into Category
        # (confirmed live from a screenshot - not a hypothetical).
        name_cell = ft.Row(
            [
                ProviderIcon(name, stream.get("icon_b64")),
                ft.Container(content=TableNameText(name), expand=True),
            ],
            spacing=Theme.Spacing.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        # DataTable sorts a control cell by its .data (see data_table.py's
        # _cell_text) - a Row has no .value of its own the way the plain
        # TableNameText this replaced did, so Name would silently stop
        # sorting without this.
        name_cell.data = name
        label, color, tooltip = _HEALTH_STYLE.get(
            stream.get("staleness", "fresh"), _HEALTH_STYLE["fresh"]
        )
        if stream.get("staleness") == "stale" and stream.get("last_date"):
            tooltip = f"Last matched {stream['last_date']} - probably not a live bill anymore."
        health_cell = status_dot(label, color, tooltip)
        cells: list = [
            name_cell,
            SecondaryText(_category_leaf(stream.get("category_name") or "") or "—"),
            SecondaryText(stream.get("account_name") or "—"),
            NumericText(_usd(amount), color=Theme.Colors.TEXT_PRIMARY),
            SecondaryText(cadence),
            date_cell(stream.get("next_expected_date"), SecondaryText),
            health_cell,
        ]
        if with_status:
            cells.append(status_control)
        if with_actions:
            cells.append(ft.Row(actions, spacing=Theme.Spacing.SM))
        return cells

    def _filtered_items(self) -> list[dict]:
        """Account filter + search + date-range applied to the last fetch
        - see __init__ for why this is local filtering, not a re-fetch."""
        items = [
            s for s in self._items if self._account_filter.allows(s.get("account_id"))
        ]
        if self._query.strip():
            # The same values the row renders - name, category, account,
            # amount, cadence, next due - so "if you can see it, you can
            # search it" (see row_matches).
            items = [
                s
                for s in items
                if row_matches(
                    self._query,
                    (
                        s.get("name"),
                        s.get("category_name"),
                        s.get("account_name"),
                        _usd(s.get("expected_amount") or s.get("average_amount") or 0),
                        _frequency_label(s.get("frequency", "")),
                        format_date(s.get("next_expected_date")),
                    ),
                )
            ]
        if self._range_days < 9000:
            cutoff = date.today() - timedelta(days=self._range_days)

            def _in_range(stream: dict) -> bool:
                last = stream.get("last_date")
                # No activity recorded yet (a just-declared bill) - a date
                # filter has nothing to judge it against, so it stays
                # rather than getting silently dropped.
                return date.fromisoformat(last) >= cutoff if last else True

            items = [s for s in items if _in_range(s)]
        return items
