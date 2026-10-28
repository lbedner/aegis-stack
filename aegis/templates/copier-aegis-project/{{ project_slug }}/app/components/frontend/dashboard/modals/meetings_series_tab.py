"""Meetings > Series in the Flet Overseer: what each series of meetings
(one link, met again and again) keeps coming back to, every owner's,
beside a pane that reads the selected series, a tab per part (its facts
and summary, its run over time, then each theme with its lines:
``meetings_threads``) and writes it again,
following it while it is being written. The same as the htmx Overseer's
Series drawer, over the admin API (``api/meetings/series.py``).
"""

from __future__ import annotations

from typing import Any

import flet as ft

from app.components.frontend.controls import DataTableColumn, PrimaryText
from app.components.frontend.controls.buttons import PulseButton
from app.components.frontend.controls.tabs import OVERVIEW
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import counted, format_date

from .meetings_follow import (
    ListBesidePane,
    PartTabs,
    WrittenPane,
    details,
    hint,
    summary,
)
from .meetings_threads import thread_controls

API = "/api/v1/meetings/admin/series"


def series_cells(row: dict[str, Any]) -> list[str]:
    """One series' row (``SeriesRow``): what it is called, whose, how many
    meetings it was read from, when written."""
    series = row["series"]
    return [
        str(row.get("name") or ""),
        str(series.get("owner_user_id") or "-"),
        str(series.get("meetings") or 0),
        format_date(series.get("written_at")) or "-",
    ]


def series_view(record: dict[str, Any], *, selected: str = OVERVIEW) -> PartTabs:
    """One series read in full (``SeriesRecord``), a tab per part: where it
    was read from and its headline; its run over time a part at a time
    (settled, shifted, still open, the mood); what it keeps coming back to."""
    series = record["series"]
    facts = [
        ("Owner", series.get("owner_user_id")),
        ("Link", series.get("link")),
        ("Read from", counted(int(series.get("meetings") or 0), "meeting")),
        ("Written by", series.get("model_name")),
    ]
    overview: list[ft.Control] = [details(facts)]
    if series.get("error"):
        overview.append(
            PrimaryText(
                f"The last write failed: {series['error']}",
                size=Theme.Typography.BODY,
                color=Theme.Colors.ERROR,
            )
        )
    if record.get("writing"):
        overview.append(hint("Writing the series…"))
    overview.append(summary(str(series.get("summary") or "Nothing yet.")))
    return PartTabs(
        {
            OVERVIEW: overview,
            "Over time": thread_controls(record.get("over_time") or []),
            "Themes": thread_controls(record.get("sections") or []),
        },
        selected=selected,
    )


class SeriesPane(WrittenPane):
    """The selected series, read from the API, written again from here and
    followed while it is being written, on the tab the reader left it at."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(page, API, "Select a series")
        self._view: PartTabs | None = None

    def record_id(self, record: dict[str, Any]) -> int:
        return int(record["series"]["id"])

    def draw(self, record: dict[str, Any]) -> None:
        series_id = self.record_id(record)
        controls: list[ft.Control] = [
            PrimaryText(str(record.get("name") or ""), size=Theme.Typography.H3)
        ]
        if record.get("can_write"):
            controls.append(
                ft.Row(
                    [
                        PulseButton(
                            on_click_callable=lambda: self.write_again(
                                series_id, "write", "This series cannot be written now"
                            ),
                            text="Write it again",
                            variant="muted",
                            compact=True,
                        )
                    ]
                )
            )
        self._view = series_view(
            record, selected=self._view.picked if self._view else OVERVIEW
        )
        controls.append(self._view)
        self.content = ft.Column(controls, spacing=Theme.Spacing.MD, expand=True)
        if self.page:
            self.update()


class SeriesTab(ListBesidePane):
    """Every owner's series, latest written first, beside the selected one."""

    def __init__(self, page: ft.Page) -> None:
        super().__init__(
            page,
            API,
            SeriesPane(page),
            columns=[
                DataTableColumn("Series", width=220, style="primary"),
                DataTableColumn("Owner", width=80, style="secondary"),
                DataTableColumn("Meetings", width=90, style="secondary"),
                DataTableColumn("Written", width=120, style="secondary"),
            ],
            cells=series_cells,
            id_of=lambda row: int(row["series"]["id"]),
            loading="Loading series...",
            empty=(
                "No series yet: one is written once a second meeting on the"
                " same link has notes."
            ),
        )
