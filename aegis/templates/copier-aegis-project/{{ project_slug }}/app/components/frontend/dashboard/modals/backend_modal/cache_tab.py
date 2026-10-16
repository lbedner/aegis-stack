"""Cache tab for the backend modal.

What is in the cache, grouped by what it is for: how much room each kind
takes and whether it earns it. The same view as the htmx Server
page's Cache section, built by the same helper
(``app.services.system.ui_cache``). The dashboard runs in the webserver
process, so the hit and miss counts are that process's.
"""

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
from app.services.system.models import CacheGroup, CacheKey, CacheView

from ..modal_sections import MetricCard


class CacheTab(ft.Container):
    """Tab body: cache figures, kinds by room taken, largest keys."""

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

    def _render(self, view: CacheView) -> None:
        if view.error:
            self._message(
                "The cache could not be read", f"{view.backend}: {view.error}"
            )
            return
        if not view.groups:
            self._message(
                "The cache is empty",
                "Services put values here with app.core.cache; "
                "they appear once something is cached.",
            )
            return
        backend = view.backend
        cards = [
            MetricCard(
                value=str(figure["value"]), label=figure["label"], color=ft.Colors.BLUE
            )
            for figure in view.figures
        ]
        self._body.content = ft.Column(
            [
                ft.Row(cards, spacing=Theme.Spacing.MD),
                SecondaryText(
                    "Backend: Redis (shared by every process)"
                    if backend == "redis"
                    else "Backend: memory (this process only)"
                ),
                H3Text("What it holds"),
                self._groups(view.groups),
                H3Text("Largest keys"),
                self._largest(view.largest),
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
    def _groups(groups: list[CacheGroup]) -> ft.Control:
        columns = [
            DataTableColumn("Kind", style="primary"),
            DataTableColumn("Keys", width=80, alignment="right"),
            DataTableColumn("Size", width=100, alignment="right"),
            DataTableColumn("Share", width=80, alignment="right"),
            DataTableColumn("Hit rate", width=100, alignment="right"),
        ]
        rows = [
            ExpandableRow(
                cells=[
                    g.name,
                    f"{g.keys:,}",
                    g.size,
                    f"{g.share * 100:.0f}%",
                    f"{g.hit_rate}%" if g.hit_rate is not None else "-",
                ],
                expanded_content=ft.Row(
                    [
                        ft.Column([SecondaryText(label), BodyText(value)], spacing=2)
                        for label, value in (
                            ("For", g.about or "-"),
                            ("Hits", f"{g.reads.hits:,}"),
                            ("Misses", f"{g.reads.misses:,}"),
                            ("Avg time left", g.ttl_label or "-"),
                        )
                    ],
                    spacing=Theme.Spacing.LG,
                ),
            )
            for g in groups
        ]
        return ExpandableDataTable(columns=columns, rows=rows, row_padding=8)

    @staticmethod
    def _largest(largest: list[CacheKey]) -> ft.Control:
        columns = [
            DataTableColumn("Key", style="primary"),
            DataTableColumn("Size", width=100, alignment="right"),
            DataTableColumn("Time left", width=120, alignment="right"),
        ]
        rows = [
            ExpandableRow(
                cells=[k.key, k.size, k.ttl_label or "-"],
                expanded_content=SecondaryText(f"Kind: {k.group}"),
            )
            for k in largest
        ]
        return ExpandableDataTable(columns=columns, rows=rows, row_padding=8)
