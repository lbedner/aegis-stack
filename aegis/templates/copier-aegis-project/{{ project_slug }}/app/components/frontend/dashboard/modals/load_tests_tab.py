"""Load Tests tab for the backend modal.

Fetches recent HTTP load-test runs from ``/api/v1/load-tests/api/recent``
(populated by ``APILoadTestService.run`` when invoked through the CLI or
elsewhere) and renders them as an ``ExpandableDataTable`` mirroring the
PerformanceTab pattern: summary ``MetricCard`` row at the top, table
below, per-row expanded detail.

Empty state renders when no Redis is configured or no runs exist — the
tab gracefully shows guidance instead of an error.
"""

from typing import Any

import flet as ft

from app.components.frontend.controls import (
    BodyText,
    DataTableColumn,
    ExpandableDataTable,
    ExpandableRow,
    H3Text,
    MethodBadge,
    SecondaryText,
)
from app.components.frontend.theme import AegisTheme as Theme
from app.core.formatting import format_relative_time
from app.services.system import ui_backend

from .modal_sections import MetricCard


class LoadTestsTab(ft.Container):
    """Tab body: recent HTTP load-test runs + per-run drill-down."""

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
        from app.components.frontend.state.session_state import get_session_state

        runs: list[dict[str, Any]] = []
        try:
            client = get_session_state(self.page).api_client
            fetched = await client.get("/api/v1/load-tests/api/recent?limit=50")
            if isinstance(fetched, list):
                runs = fetched
        except Exception:
            # Empty state still renders, just without live data
            pass

        self._render(runs)
        self._body.update()

    def _render(self, runs: list[dict[str, Any]]) -> None:
        if not runs:
            self._body.content = ft.Column(
                [
                    H3Text("No HTTP load-test runs yet"),
                    SecondaryText(
                        "Kick off a run from the CLI: "
                        "`my-app api-load-test run /health --in-process`. "
                        "Results land here automatically."
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=Theme.Spacing.SM,
            )
            self._body.alignment = ft.alignment.center
            self._body.padding = ft.padding.all(Theme.Spacing.LG)
            return

        summary_cards = self._build_summary_cards(runs)

        columns = [
            DataTableColumn("Method", width=80),
            DataTableColumn("Path", style="primary"),
            DataTableColumn("Req/s", width=90, alignment="right"),
            DataTableColumn("p95 ms", width=90, alignment="right"),
            DataTableColumn("Err %", width=80, alignment="right"),
            DataTableColumn("When", width=180),
        ]

        rows = [self._build_run_row(run) for run in runs]
        table = ExpandableDataTable(
            columns=columns,
            rows=rows,
            row_padding=8,
            empty_message="No load-test runs recorded",
        )

        self._body.content = ft.Column(
            [
                ft.Row(summary_cards, spacing=Theme.Spacing.MD),
                ft.Container(height=Theme.Spacing.SM),
                H3Text("Recent runs"),
                ft.Container(content=table, expand=True),
            ],
            spacing=Theme.Spacing.SM,
            scroll=ft.ScrollMode.AUTO,
        )
        self._body.alignment = None
        self._body.padding = None

    @staticmethod
    def _build_summary_cards(runs: list[dict[str, Any]]) -> list[ft.Control]:
        summary = ui_backend.load_test_summary(runs)
        total_runs = summary["runs"]
        avg_throughput = summary["throughput"]
        avg_p95 = summary["p95"]
        failures = summary["failures"]

        return [
            MetricCard(
                value=str(total_runs),
                label="Runs",
                color=ft.Colors.BLUE,
            ),
            MetricCard(
                value=f"{avg_throughput:.0f}",
                label="Avg req/s",
                color=Theme.Colors.SUCCESS,
            ),
            MetricCard(
                value=f"{avg_p95:.1f}",
                label="Avg p95 ms",
                color=ft.Colors.AMBER,
            ),
            MetricCard(
                value=str(failures),
                label="Total failures",
                color=ft.Colors.ERROR if failures else ft.Colors.GREY,
            ),
        ]

    @staticmethod
    def _build_run_row(run: dict[str, Any]) -> ExpandableRow:
        config = run.get("configuration") or {}
        metrics = run.get("metrics") or {}
        method = str(config.get("method", ""))
        path = str(config.get("path", ""))
        throughput = float(metrics.get("overall_throughput", 0.0) or 0.0)
        p95 = float(metrics.get("latency_ms_p95", 0.0) or 0.0)
        failure_rate = float(metrics.get("failure_rate_percent", 0.0) or 0.0)
        when = format_relative_time(run.get("start_time"))

        cells = [
            MethodBadge(method),
            path,
            f"{throughput:.0f}",
            f"{p95:.1f}",
            f"{failure_rate:.1f}%",
            when,
        ]
        return ExpandableRow(
            cells=cells,
            expanded_content=LoadTestsTab._build_expanded(run),
        )

    @staticmethod
    def _build_expanded(run: dict[str, Any]) -> ft.Control:
        config = run.get("configuration") or {}
        metrics = run.get("metrics") or {}

        def _stat(label: str, value: str) -> ft.Control:
            return ft.Column(
                [SecondaryText(label), BodyText(value)],
                spacing=2,
            )

        latency_row = ft.Row(
            [
                _stat("p50 ms", f"{float(metrics.get('latency_ms_p50', 0.0)):.1f}"),
                _stat("p95 ms", f"{float(metrics.get('latency_ms_p95', 0.0)):.1f}"),
                _stat("p99 ms", f"{float(metrics.get('latency_ms_p99', 0.0)):.1f}"),
                _stat("max ms", f"{float(metrics.get('latency_ms_max', 0.0)):.1f}"),
                _stat(
                    "Total duration",
                    f"{float(metrics.get('total_duration_seconds', 0.0)):.3f}s",
                ),
            ],
            spacing=Theme.Spacing.LG,
            wrap=True,
        )

        sent = int(metrics.get("tasks_sent", 0) or 0)
        completed = int(metrics.get("tasks_completed", 0) or 0)
        failed = int(metrics.get("tasks_failed", 0) or 0)
        counts_row = ft.Row(
            [
                _stat("Requests", str(sent)),
                _stat("Success", str(completed)),
                _stat("Failed", str(failed)),
                _stat("Clients", str(int(config.get("clients", 0) or 0))),
                _stat("Test ID", str(run.get("test_id", "-"))),
            ],
            spacing=Theme.Spacing.LG,
            wrap=True,
        )

        status_codes = metrics.get("status_codes") or {}
        status_text = (
            ", ".join(
                f"{code}: {count}" for code, count in sorted(status_codes.items())
            )
            or "—"
        )

        errors = metrics.get("errors") or []
        error_lines: list[ft.Control] = []
        if errors:
            error_lines.append(SecondaryText(f"Error samples ({len(errors)})"))
            for sample in errors[:5]:
                error_lines.append(
                    BodyText(
                        f"#{sample.get('request_index', '?')} "
                        f"{sample.get('error_type', '?')}: "
                        f"{sample.get('message', '')[:200]}"
                    )
                )
            if len(errors) > 5:
                error_lines.append(SecondaryText(f"... and {len(errors) - 5} more"))

        return ft.Column(
            [
                latency_row,
                counts_row,
                ft.Row(
                    [SecondaryText("Status codes:"), BodyText(status_text)],
                    spacing=Theme.Spacing.SM,
                ),
                *error_lines,
            ],
            spacing=Theme.Spacing.SM,
        )
