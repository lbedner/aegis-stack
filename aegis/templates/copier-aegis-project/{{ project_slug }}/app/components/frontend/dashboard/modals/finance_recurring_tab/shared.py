"""Vocabulary the Bills & Income surfaces share.

Columns, pause labels, status keys, and the projection layout math -
used by the tab, the projection panel, and their tests.
"""

from __future__ import annotations

from datetime import date

import flet as ft

from app.components.frontend.controls.data_table import DataTableColumn
from app.components.frontend.theme import AegisTheme as Theme

_RECURRING_URL = "/api/v1/finance/recurring"


# Name is the width-less column: it absorbs whatever the modal has left,
# so the table fills its panel instead of stranding empty space rightward.
# An Actions column is appended per-table, only when a row has a verb to
# offer (Confirm, on unapproved outflows) - Bills and Income have none.
# Health (staleness) is always shown, unlike the curation-state Status
# column appended below - it's a second, separate signal (still real vs.
# gone quiet), not a replacement for it.
_COLUMNS = [
    DataTableColumn("Name", style="body", hideable=False),
    DataTableColumn("Category", width=150, style="secondary"),
    DataTableColumn("Account", width=150, style="secondary"),
    DataTableColumn("Amount", width=110, alignment="right", style="secondary"),
    DataTableColumn("Cadence", width=160, style="secondary"),
    DataTableColumn("Next due", width=110, style="secondary"),
    DataTableColumn("Health", width=100),
]


_NEXT_DUE_COLUMN = 5


# ASCENDING: this page answers "what is coming up", so the first row has
# to be the next thing due. Descending put the furthest-away bill at the
# top and the one due tomorrow below the fold. Blanks are unaffected -
# DataTable's type-ranked key sorts them last either way, which is where
# a bill with no due date belongs on a list about what is next.
_NEXT_DUE_SORT_DESC = False


def _usd(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.2f}"


def _usd_signed(cents: int, *, plus: bool = False) -> str:
    """Signed money: ``-$115.35``, and ``+$1,200.00`` when ``plus`` is on."""
    sign = "-" if cents < 0 else ("+" if plus else "")
    return f"{sign}{_usd(abs(cents))}"


def _is_curated(stream: dict) -> bool:
    """A stream the user personally vouched for - THE RECORD.

    ``is_subscription`` no longer counts: it is the detector's own guess
    (plus the Quicken-category promote pass), and honouring it here put
    71 rows nobody confirmed into Bills - which is how a 2019 Capital One
    auto-payment sat in the user's "real bills" charging the forecast.
    Bills/Income = what you set. Everything else waits in Detected for
    the Confirm that is now the single door in.
    """
    return bool(stream.get("source") == "user" or stream.get("is_user_confirmed"))


def pause_options(today: date) -> list[tuple[str, date]]:
    """The pause dialog's quick picks, as real calendar months.

    ``add_months`` (the cadence engine's own stepper) rather than day
    arithmetic: "3 months" from Aug 9 is Nov 9, and from Aug 31 it clamps
    to the shorter month instead of drifting into the next one.
    """
    from app.services.finance.constants import add_months

    return [
        (f"{n} month{'s' if n > 1 else ''}", add_months(today, n)) for n in (1, 2, 3, 6)
    ]


def pause_label(until_iso: str) -> str:
    """ "until Nov 9" or "indefinitely" - the year 9999 is an
    implementation detail nobody should ever read."""
    from app.services.finance.constants import PAUSE_INDEFINITE

    if date.fromisoformat(str(until_iso)) >= PAUSE_INDEFINITE:
        return "indefinitely"
    return f"until {until_iso}"


def stream_is_paused(stream: dict) -> bool:
    """The frontend half of ``is_paused``: same lazy comparison, read off
    the response dict."""
    until = stream.get("paused_until")
    if not until:
        return False
    return date.today() < date.fromisoformat(str(until))


def _status_key(stream: dict) -> str:
    """The status a row WOULD show. Used to decide whether the Status
    column earns its place: on a tab where every row reads the same, the
    column is 88 copies of a word the tab title already said."""
    if stream.get("is_muted"):
        return "muted"
    if stream_is_paused(stream):
        return "paused"
    if stream.get("is_payment"):
        return "payment"
    if stream.get("direction") == "inflow":
        return "income"
    if _is_curated(stream):
        return "good"
    return "detected"


def projection_columns() -> list[DataTableColumn]:
    """The projection ledger's columns: Date, Name, Amount, Balance.

    Category and Account ship hidden (one click away in the picker).
    That is a WIDTH budget, not a taste call: the ledger gets 9/20 of
    the modal, ~565px on a small laptop, and a flex column gets only
    what the fixed ones leave. With Category visible the fixed widths
    plus the picker gutter and spacing overflowed that share, so the one
    flex column - Name, the identity column - silently rendered at ZERO
    width and the ledger showed category strings where bill names
    belong. Confirmed live at 1459px; the control tree looks correct the
    whole time, which is why only the width-budget test can hold the
    line. (``build_cell``'s docstring records the same collapse shipping
    twice before in other tables.)
    """
    # Widths sized to their real content ("Aug 15, 2026", "-$14,349.00"),
    # not round numbers - every spare pixel here is Name width.
    return [
        DataTableColumn("Date", width=100, style="secondary"),
        DataTableColumn("Name", style="body", hideable=False),
        DataTableColumn("Category", width=170, style="secondary", visible=False),
        DataTableColumn("Account", width=170, style="secondary", visible=False),
        DataTableColumn("Amount", width=110, alignment="right"),
        DataTableColumn("Balance", width=120, alignment="right"),
    ]


def projection_layout(chart: ft.Control, table: ft.Control) -> ft.Row:
    """Chart beside the ledger, not above it.

    Stacked, the chart ate the height and left the ledger ~4 visible
    rows. The two halves answer one question together - the line says
    WHEN the balance turns, the rows say WHAT turns it - so they share
    the width rather than hiding one behind a sub-tab. The chart keeps
    the wider share (a compressed date axis stops being readable before
    a table does); the ledger gets the full tab height.

    ``expand=True`` on the Row is load-bearing, not styling: STRETCH
    against an unbounded parent renders NOTHING in Flet's release build
    (the import-review dialog shipped exactly that bug).
    """
    return ft.Row(
        [
            ft.Container(content=chart, expand=11),
            ft.Container(content=table, expand=9),
        ],
        spacing=Theme.Spacing.MD,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        expand=True,
    )
