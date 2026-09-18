"""The Performance tab: per-endpoint timings, loaded on mount.

The only tab that fetches. It paints a placeholder, asks the API for
endpoint statistics, and re-renders; a row expands into the percentile
breakdown behind its average.
"""

import flet as ft
from app.components.frontend.controls import (
    BodyText,
    H3Text,
    MethodBadge,
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


class PerformanceTab(ft.Container):
    """Per-endpoint response-time table backed by the in-memory metrics service.

    Fetches ``/api/v1/metrics/summary`` and ``/api/v1/metrics/endpoints``
    in ``did_mount`` (i.e. each time the modal is opened) rather than
    reading the snapshot embedded in the health-poll payload. The
    snapshot can be up to one dashboard-refresh interval old; live
    fetch shows counts as of the open. Backend is excluded from the
    modal cache (see ``card_utils._open_modal``) so ``did_mount``
    fires on every open.
    """

    def __init__(self, backend_component: ComponentStatus) -> None:
        super().__init__()
        # Seed values from the health snapshot. They render instantly
        # under the loading spinner so the tab isn't visually empty
        # while the fresh fetch is in flight, and they're also the
        # fallback if the metrics endpoint is unreachable.
        metadata = backend_component.metadata or {}
        self._initial_summary: dict = metadata.get("performance") or {}
        self._initial_endpoints: dict = metadata.get("performance_endpoints") or {}

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
        # Flet fires did_mount once per add-to-page. Backend's modal is
        # excluded from _modal_cache, so every open creates a fresh
        # PerformanceTab and this fires again.
        self.page.run_task(self._load)

    async def _load(self) -> None:
        from app.components.frontend.state.session_state import get_session_state

        summary: dict = dict(self._initial_summary)
        endpoints: dict = dict(self._initial_endpoints)
        try:
            client = get_session_state(self.page).api_client
            fresh_summary = await client.get("/api/v1/metrics/summary")
            fresh_endpoints = await client.get("/api/v1/metrics/endpoints")
            if isinstance(fresh_summary, dict):
                summary = fresh_summary
            if isinstance(fresh_endpoints, dict):
                endpoints = fresh_endpoints
        except Exception:
            # Fall back to whatever the health snapshot carried — the
            # tab still renders, just at one poll-interval of staleness.
            pass

        self._render(summary, endpoints)
        self._body.update()

    def _render(self, summary: dict, endpoints: dict) -> None:
        total_requests = int(summary.get("total_requests", 0) or 0)

        if total_requests == 0 or not endpoints:
            self._body.content = ft.Column(
                [
                    H3Text("No requests recorded yet"),
                    SecondaryText(
                        "Hit a few endpoints, then reopen this tab — "
                        "metrics are kept in memory for the life of "
                        "the process."
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
                value=str(total_requests),
                label="Total Requests",
                color=ft.Colors.BLUE,
            ),
            MetricCard(
                value=str(summary.get("tracked_endpoints", 0)),
                label="Tracked Endpoints",
                color=Theme.Colors.SUCCESS,
            ),
            MetricCard(
                value=f"{float(summary.get('avg_ms', 0.0) or 0.0):.1f}",
                label="Avg ms",
                color=ft.Colors.PURPLE,
            ),
            MetricCard(
                value=f"{float(summary.get('p95_ms', 0.0) or 0.0):.1f}",
                label="p95 ms",
                color=ft.Colors.AMBER,
            ),
        ]

        slowest = summary.get("slowest_endpoint")
        if isinstance(slowest, dict) and slowest.get("endpoint"):
            slowest_row = ft.Container(
                content=ft.Row(
                    [
                        SecondaryText("Slowest:"),
                        BodyText(str(slowest["endpoint"])),
                        SecondaryText(
                            f"{float(slowest.get('avg_ms', 0.0) or 0.0):.1f}ms avg"
                        ),
                    ],
                    spacing=Theme.Spacing.SM,
                ),
                padding=ft.padding.symmetric(
                    horizontal=Theme.Spacing.MD, vertical=Theme.Spacing.SM
                ),
            )
        else:
            slowest_row = ft.Container()

        columns = [
            DataTableColumn("Method", width=80),
            DataTableColumn("Path", style="primary"),
            DataTableColumn("Count", width=80, alignment="right"),
            DataTableColumn("Avg ms", width=90, alignment="right"),
            DataTableColumn("p95 ms", width=90, alignment="right"),
        ]
        sorted_items = sorted(
            endpoints.items(),
            key=lambda kv: int((kv[1] or {}).get("count", 0) or 0),
            reverse=True,
        )
        table_rows = [
            self._build_endpoint_row(key, stats) for key, stats in sorted_items
        ]
        table = ExpandableDataTable(
            columns=columns,
            rows=table_rows,
            row_padding=8,
            empty_message="No endpoints recorded",
        )

        self._body.content = ft.Column(
            [
                ft.Row(summary_cards, spacing=Theme.Spacing.MD),
                slowest_row,
                ft.Container(height=Theme.Spacing.SM),
                H3Text("Endpoints"),
                ft.Container(content=table, expand=True),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self._body.alignment = None
        self._body.padding = None

    @staticmethod
    def _build_endpoint_row(key: str, stats: dict) -> ExpandableRow:
        """Collapsed: method / path / count / avg / p95. Expanded: full stats."""
        stats = stats or {}
        method, _, path = key.partition(" ")
        count = int(stats.get("count", 0) or 0)
        avg_ms = float(stats.get("avg_ms", 0.0) or 0.0)
        p95_ms = float(stats.get("p95_ms", 0.0) or 0.0)

        cells = [
            MethodBadge(method),
            path or key,
            str(count),
            f"{avg_ms:.1f}",
            f"{p95_ms:.1f}",
        ]
        return ExpandableRow(
            cells=cells,
            expanded_content=PerformanceTab._build_expanded_stats(stats),
        )

    @staticmethod
    def _build_expanded_stats(stats: dict) -> ft.Control:
        """Detail view: min / median / max / p99 / last request timestamp."""
        min_ms = float(stats.get("min_ms", 0.0) or 0.0)
        median_ms = float(stats.get("median_ms", 0.0) or 0.0)
        max_ms = float(stats.get("max_ms", 0.0) or 0.0)
        p99_ms = float(stats.get("p99_ms", 0.0) or 0.0)
        last_request_at = stats.get("last_request_at") or "—"

        def _stat(label: str, value: str) -> ft.Control:
            return ft.Column(
                [SecondaryText(label), BodyText(value)],
                spacing=2,
            )

        return ft.Row(
            [
                _stat("Min ms", f"{min_ms:.1f}"),
                _stat("Median ms", f"{median_ms:.1f}"),
                _stat("Max ms", f"{max_ms:.1f}"),
                _stat("p99 ms", f"{p99_ms:.1f}"),
                _stat("Last request", str(last_request_at)),
            ],
            spacing=Theme.Spacing.LG,
            wrap=True,
        )
