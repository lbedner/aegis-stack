"""The Traffic tab: where requests came from, loaded on mount.

Fetches alongside ``PerformanceTab`` and renders a sources table under
a summary. Separate from performance because they answer different
questions off different endpoints.
"""

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    SecondaryText,
)
from app.components.frontend.controls.data_table import DataTableColumn
from app.components.frontend.controls.expandable_data_table import (
    ExpandableDataTable,
    ExpandableRow,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.services.system.models import ComponentStatus

from ..modal_sections import (
    MetricCard,
)


class TrafficTab(ft.Container):
    """Per-source request volume - the "who's hammering you" view.

    Fetches ``/api/v1/traffic/sources`` in ``did_mount``. The traffic monitor
    counts requests per client IP (Redis-backed when present, in-memory
    otherwise) and flags a source as dominant at read time, so this works
    without Redis or a scheduler - recording and reading both happen in the
    backend process. When the store is in-memory the tab notes that counts are
    per-process and reset on restart.
    """

    def __init__(self, backend_component: ComponentStatus | None = None) -> None:
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
        from app.components.frontend.state.session_state import get_session_state

        data: dict = {}
        try:
            client = get_session_state(self.page).api_client
            fresh = await client.get("/api/v1/traffic/sources")
            if isinstance(fresh, dict):
                data = fresh
        except Exception:
            # Endpoint unreachable - render the empty state, not a broken tab.
            pass

        self._render(data)
        self._body.update()

    def _render(self, data: dict) -> None:
        sources = data.get("sources") or []
        total = int(data.get("total_requests", 0) or 0)
        window_hours = int(data.get("window_hours", 24) or 24)
        backend = data.get("backend", "memory")
        dominant = data.get("dominant")

        if total == 0 and not sources:
            self._body.content = ft.Column(
                [
                    H3Text("No traffic recorded yet"),
                    SecondaryText(
                        "Source IPs show up here once requests come in. "
                        "Reopen this tab after some traffic."
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
            )
            self._body.alignment = ft.alignment.center
            self._body.padding = ft.padding.all(Theme.Spacing.LG)
            return

        summary_cards = [
            MetricCard(
                value=f"{total:,}",
                label=f"Requests / {window_hours}h",
                color=ft.Colors.BLUE,
            ),
            MetricCard(
                value=str(len(sources)),
                label="Source IPs",
                color=ft.Colors.GREEN,
            ),
            MetricCard(
                value=backend,
                label="Store",
                color=ft.Colors.PURPLE if backend == "redis" else ft.Colors.GREY,
            ),
        ]

        children: list[ft.Control] = [ft.Row(summary_cards, spacing=Theme.Spacing.MD)]

        if dominant:
            pct = int(round(float(dominant.get("share", 0.0)) * 100))
            children.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(
                                ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.WHITE
                            ),
                            BodyText(
                                f"One source is dominating: {dominant.get('ip')} "
                                f"- {pct}% of traffic "
                                f"({int(dominant.get('requests', 0)):,} requests)"
                            ),
                        ],
                        spacing=Theme.Spacing.SM,
                    ),
                    bgcolor=Theme.Colors.ERROR,
                    border_radius=6,
                    padding=ft.padding.symmetric(
                        horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
                    ),
                )
            )

        if backend != "redis":
            children.append(
                SecondaryText(
                    "In-memory store (per-process, resets on restart). "
                    "Add the Redis component for cross-process counts and "
                    "persistence."
                )
            )

        children.extend(
            [
                ft.Container(height=Theme.Spacing.SM),
                H3Text("Top source IPs"),
                ft.Container(content=self._sources_table(sources), expand=True),
            ]
        )

        self._body.content = ft.Column(
            children, spacing=Theme.Spacing.SM, scroll=ft.ScrollMode.AUTO
        )
        self._body.alignment = None
        self._body.padding = None

    @staticmethod
    def _sources_table(sources: list) -> ft.Control:
        columns = [
            DataTableColumn("Source IP", style="primary"),
            DataTableColumn("Requests", width=120, alignment="right"),
            DataTableColumn("Share", width=100, alignment="right"),
        ]
        rows = []
        for src in sources:
            share_pct = float(src.get("share", 0.0) or 0.0) * 100
            rows.append(
                ExpandableRow(
                    cells=[
                        str(src.get("ip", "-")),
                        f"{int(src.get('requests', 0) or 0):,}",
                        f"{share_pct:.0f}%",
                    ],
                    expanded_content=ft.Row(
                        [
                            ft.Column(
                                [SecondaryText("Share"), BodyText(f"{share_pct:.1f}%")],
                                spacing=2,
                            ),
                            ft.Column(
                                [
                                    SecondaryText("Requests"),
                                    BodyText(f"{int(src.get('requests', 0) or 0):,}"),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=Theme.Spacing.LG,
                    ),
                )
            )
        return ExpandableDataTable(
            columns=columns,
            rows=rows,
            row_padding=8,
            empty_message="No source IPs recorded in this window",
        )
