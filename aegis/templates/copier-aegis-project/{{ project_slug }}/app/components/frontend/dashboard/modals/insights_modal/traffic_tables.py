"""The two controls the traffic tab needs more than one of.

Ninety lines of this lived inside ``GitHubTrafficTab._build_content``,
which is how a method reaches five hundred. Only what is used more than
once becomes a type: a titled table, because referrers and paths are
the same table twice, and a linking cell, because every name in both of
them is one. Everything else is composed where it is used - the tables
are two instances rather than two classes, the row they sit in is a
row, and the rows they hold are built in the tab that has the data.
"""

from typing import Any

import flet as ft
from app.components.frontend.controls.data_table import DataTable, DataTableColumn
from app.components.frontend.controls.text import H3Text
from app.components.frontend.theme import AegisTheme as Theme

TRAFFIC_COLUMNS = [
    DataTableColumn("Source", style="primary"),
    DataTableColumn("Views", width=80, alignment="right", style="body"),
    DataTableColumn("Unique", width=80, alignment="right", style="secondary"),
]


class LinkCell(ft.Container):
    """A table cell that opens its source rather than naming it.

    Every name in both traffic tables is one of these - a referrer
    domain or a github.com path - so a reader can follow the source out
    of the modal instead of copying a URL out of it.
    """

    def __init__(self, label: str, url: str) -> None:
        super().__init__()
        self.content = ft.Text(
            label,
            size=Theme.Typography.BODY,
            style=ft.TextStyle(
                color=Theme.Colors.INFO,
                decoration=ft.TextDecoration.UNDERLINE,
            ),
            selectable=False,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.on_click = lambda e, u=url: e.page.launch_url(u)
        self.ink = True
        self.expand = True


class TrafficTable(ft.Column):
    """A titled traffic table: heading, rule, rows.

    ``SectionHeader`` is the house title row but carries no rule, and
    the rule is what separates these two tables when they sit side by
    side.
    """

    def __init__(
        self, title: str, rows: list[list[Any]], *, empty_message: str
    ) -> None:
        super().__init__()
        self.controls = [
            H3Text(title),
            ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
            DataTable(columns=TRAFFIC_COLUMNS, rows=rows, empty_message=empty_message),
        ]
        self.spacing = 6
        self.expand = 1


def referrer_url(domain: str) -> str:
    """Where a referrer name points.

    A name without a dot is not a host - GitHub reports some sources
    that way - so it searches for the name rather than linking to a URL
    that would not resolve. The rule is here because it is a rule, and
    it is the one thing in this file worth asserting on its own.
    """
    if "." in domain:
        return f"https://{domain}"
    return f"https://www.google.com/search?q={domain}"


def referrer_rows(referrers: list[dict[str, Any]]) -> list[list[Any]]:
    """Referrer records as table rows."""
    return [
        [
            LinkCell(ref["domain"], referrer_url(ref["domain"])),
            f"{ref['views']:,}",
            f"{ref['uniques']:,}",
        ]
        for ref in referrers
    ]


def path_rows(paths: list[dict[str, Any]]) -> list[list[Any]]:
    """Popular-path records as table rows."""
    return [
        [
            LinkCell(p["path"], f"https://github.com{p['path']}"),
            f"{p['views']:,}",
            f"{p['uniques']:,}",
        ]
        for p in paths
    ]
