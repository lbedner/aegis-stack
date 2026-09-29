"""Cache tab for the backend modal.

What is in the cache, by family (the first two parts of a key): how much
room each takes and whether it earns it. The same view as the htmx Server
page's Cache section, built by the same helper
(``app.services.system.ui_cache``). The dashboard runs in the webserver
process, so the hit and miss counts are that process's.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DataTableColumn,
    ExpandableDataTable,
    ExpandableRow,
    H3Text,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system import ui_cache

from ..modal_sections import MetricCard


class CacheTab(ft.Container):
    """Tab body: cache figures, families by room taken, largest keys."""

    def __init__(self) -> None:
        super().__init__()
        self._body = ft.Container(
            content=ft.Row(
                [ft.ProgressRing(width=20, height=20)],
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            alignment=ft.alignment.center,
            expand=True,
            padding=ft.padding.all(Theme.Spacing.LG),
        )
        self.content = self._body
        self.padding = ft.padding.all(Theme.Spacing.MD)

    def did_mount(self) -> None:
        self.page.run_task(self._load)

    async def _load(self) -> None:
        self._render(await ui_cache.load())
        self._body.update()

    def _render(self, view: dict[str, Any]) -> None:
        if view.get("error"):
            self._message(
                "The cache could not be read",
                f"{view.get('backend', '')}: {view['error']}",
            )
            return
        if not view["families"]:
            self._message(
                "The cache is empty",
                "Services put values here with app.core.cache; "
                "they appear once something is cached.",
            )
            return
        backend = view["backend"]
        cards = [
            MetricCard(
                value=str(figure["value"]), label=figure["label"], color=ft.Colors.BLUE
            )
            for figure in view["figures"]
        ]
        self._body.content = ft.Column(
            [
                ft.Row(cards, spacing=Theme.Spacing.MD),
                SecondaryText(
                    "Backend: Redis (shared by every process)"
                    if backend == "redis"
                    else "Backend: memory (this process only)"
                ),
                H3Text("Families"),
                self._families(view["families"]),
                H3Text("Largest keys"),
                self._largest(view["largest"]),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self._body.alignment = None
        self._body.padding = None

    def _message(self, title: str, detail: str) -> None:
        self._body.content = ft.Column(
            [H3Text(title), SecondaryText(detail)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=Theme.Spacing.SM,
        )

    @staticmethod
    def _families(families: list[dict[str, Any]]) -> ft.Control:
        columns = [
            DataTableColumn("Family", style="primary"),
            DataTableColumn("Keys", width=80, alignment="right"),
            DataTableColumn("Size", width=100, alignment="right"),
            DataTableColumn("Share", width=80, alignment="right"),
            DataTableColumn("Hit rate", width=100, alignment="right"),
        ]
        rows = [
            ExpandableRow(
                cells=[
                    f["family"],
                    f"{f['keys']:,}",
                    f["size"],
                    f"{f['share'] * 100:.0f}%",
                    f"{f['hit_rate']}%" if f["hit_rate"] is not None else "-",
                ],
                expanded_content=ft.Row(
                    [
                        ft.Column([SecondaryText(label), BodyText(value)], spacing=2)
                        for label, value in (
                            ("Hits", f"{f['hits']:,}"),
                            ("Misses", f"{f['misses']:,}"),
                            ("Avg time left", f["ttl_label"]),
                        )
                    ],
                    spacing=Theme.Spacing.LG,
                ),
            )
            for f in families
        ]
        return ExpandableDataTable(columns=columns, rows=rows, row_padding=8)

    @staticmethod
    def _largest(largest: list[dict[str, Any]]) -> ft.Control:
        columns = [
            DataTableColumn("Key", style="primary"),
            DataTableColumn("Size", width=100, alignment="right"),
            DataTableColumn("Time left", width=120, alignment="right"),
        ]
        rows = [
            ExpandableRow(
                cells=[k["key"], k["size"], k["ttl_label"]],
                expanded_content=SecondaryText(f"Family: {k['family']}"),
            )
            for k in largest
        ]
        return ExpandableDataTable(columns=columns, rows=rows, row_padding=8)
