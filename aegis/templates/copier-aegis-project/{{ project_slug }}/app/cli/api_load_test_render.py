"""Progress while a run goes, and the table when it finishes."""

from __future__ import annotations

from typing import Any

from app.cli import theme
from app.services.load_test.api.models import (
    APILoadTestResult,
)


def _progress_console() -> Any:
    """Rich console themed for the progress bar: brand-teal bar/spinner so
    completion reads as good-state, dim timers so the chrome stays quiet."""
    from rich.console import Console
    from rich.theme import Theme

    return Console(
        highlight=False,
        theme=Theme(
            {
                "bar.complete": theme.ACCENT,
                "bar.finished": theme.ACCENT,
                "bar.pulse": theme.ACCENT,
                "progress.spinner": theme.ACCENT,
                "progress.elapsed": "dim",
                "progress.remaining": "dim",
            }
        ),
    )


console = theme.console()


_METHOD_COLORS_CLI: dict[str, str] = {
    "GET": "dim",
    "POST": "dim",
    "PUT": "dim",
    "PATCH": "dim",
    "DELETE": "dim",
}


def _method_color(method: str) -> str:
    return _METHOD_COLORS_CLI.get(method, "dim")


def _render_result(r: APILoadTestResult) -> None:
    """Render a single load-test result.

    The report describes what the load test observed; it deliberately does
    NOT pronounce pass / fail. A load test that completed all its requests
    succeeded as a test, regardless of how the endpoint responded. Use the
    status-code distribution and Errors count below to judge whether the
    endpoint behaved as expected; gate CI on it yourself via ``--json``.
    """
    config = r.configuration
    m = r.metrics

    console.print()
    console.print(f"[dim]Test ID:[/dim] {r.test_id}")
    console.print(f"[dim]Target:[/dim]  {config.method} {config.path}")

    # Colored success / errors so the stats density reads at a glance,
    # but with no verdict implied.
    if m.tasks_completed == m.tasks_sent:
        success_markup = (
            f"[{theme.ACCENT}]{m.tasks_completed}  (100.0%)[/{theme.ACCENT}]"
        )
    elif m.tasks_completed == 0:
        success_markup = f"[{theme.ERROR}]{m.tasks_completed}  (0.0%)[/{theme.ERROR}]"
    else:
        success_markup = (
            f"[{theme.WARNING}]{m.tasks_completed}  "
            f"({m.completion_percentage:.1f}%)[/{theme.WARNING}]"
        )
    errors_markup = (
        f"[{theme.ERROR}]{m.tasks_failed}[/{theme.ERROR}]"
        if m.tasks_failed
        else str(m.tasks_failed)
    )

    console.print()
    console.print("[bold]Results[/bold]")
    console.print(f"  [dim]Throughput[/dim]        {m.overall_throughput:.1f} req/s")
    console.print(f"  [dim]Total duration[/dim]    {m.total_duration_seconds:.3f}s")
    console.print(f"  [dim]Success[/dim]           {success_markup}")
    console.print(f"  [dim]Errors[/dim]            {errors_markup}")
    console.print()
    console.print("[bold]Latency (ms)[/bold]")
    console.print(f"  [dim]p50[/dim]    {m.latency_ms_p50:.1f}")
    console.print(f"  [dim]p95[/dim]    {m.latency_ms_p95:.1f}")
    console.print(f"  [dim]p99[/dim]    {m.latency_ms_p99:.1f}")
    console.print(f"  [dim]max[/dim]    {m.latency_ms_max:.1f}")
    if m.status_codes:
        console.print()
        console.print("[bold]Status codes[/bold]")
        for status, count in sorted(m.status_codes.items()):
            color = (
                theme.ACCENT
                if 200 <= status < 400
                else theme.WARNING
                if 400 <= status < 500
                else theme.ERROR
            )
            console.print(f"  [{color}]{status}[/{color}]    {count}")
