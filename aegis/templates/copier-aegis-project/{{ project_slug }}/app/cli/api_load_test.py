"""API load testing CLI commands.

Thin wrapper around ``APILoadTestService`` and ``discovery.list_routes``.
The CLI does no I/O itself; it constructs a config, hands it to the
service, and renders the result. This keeps the CLI testable in isolation
(see ``tests/cli/test_api_load_test_cli.py``) — production wiring
happens through ``_get_fastapi_app`` and ``_make_store``, both mockable.

The CLI subcommand is ``api-load-test``. The underlying transport is
still HTTP (httpx) and the service layer is named ``load_test.api`` to
match — that's an internal detail; the CLI surface uses "api" because
that's what users are testing.
"""

from __future__ import annotations

import asyncio
import json as json_lib
import sys
from typing import TYPE_CHECKING

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
import typer

from app.cli import theme
from app.cli.api_load_test_auth import _get_auth_dependency, apply_auto_auth
from app.cli.api_load_test_render import (
    _method_color,
    _progress_console,
    _render_result,
)
from app.cli.api_load_test_store import _with_store
from app.core.formatting import format_relative_time
from app.services.load_test.api.discovery import list_routes
from app.services.load_test.api.models import (
    APILoadTestConfiguration,
)
from app.services.load_test.api.service import APILoadTestService

if TYPE_CHECKING:
    from fastapi import FastAPI

app = typer.Typer(
    name="api-load-test",
    help="Run load tests against any endpoint in this project's FastAPI app.",
    no_args_is_help=True,
)

console = theme.console()


def _get_fastapi_app() -> FastAPI:
    """Lazily import + construct the project's FastAPI app.

    Kept as a separate function so tests can mock it without booting the
    real integrated app (which would trigger lifespan, DB connections,
    etc.).
    """
    from app.integrations.main import create_integrated_app

    return create_integrated_app()


def parse_kv_flag(items: list[str], flag_name: str) -> dict[str, str]:
    """Parse repeated ``KEY=VALUE`` flags (``--header``, ``--path-param``).

    Centralized so the error message points at the actual flag the user
    typed.
    """
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(f"{flag_name} must be KEY=VALUE, got: {item!r}")
        key, _, value = item.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def parse_headers(items: list[str]) -> dict[str, str]:
    return parse_kv_flag(items, "--header")


# The HTTP method is metadata in the route listing, not a state, so it
# renders dim (annotation) rather than carrying its own hue.


@app.command(name="list")
def list_command(
    json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List FastAPI routes discoverable for load testing."""
    fastapi_app = _get_fastapi_app()
    routes = list_routes(fastapi_app, auth_dependency=_get_auth_dependency())

    if json:
        print(json_lib.dumps([r.model_dump() for r in routes]))
        return

    if not routes:
        console.print("No routes discovered.")
        return

    has_params = any(r.path_params for r in routes)

    table = Table(
        title=f"Discovered {len(routes)} routes",
        header_style="bold",
    )
    table.add_column("METHOD")
    table.add_column("PATH", style=theme.ACCENT)
    table.add_column("AUTH")
    if has_params:
        table.add_column("PARAMS", style="dim")
    table.add_column("TAGS", style="dim")
    for r in routes:
        method_color = _method_color(r.method)
        auth_cell = (
            f"[{theme.ACCENT}]yes[/{theme.ACCENT}]"
            if r.requires_auth
            else "[dim]no[/dim]"
        )
        cells: list[str] = [
            f"[{method_color}]{r.method}[/{method_color}]",
            r.path,
            auth_cell,
        ]
        if has_params:
            cells.append(", ".join(r.path_params))
        cells.append(", ".join(r.tags))
        table.add_row(*cells)
    console.print(table)


@app.command()
def run(
    path: str = typer.Argument(..., help="Path to load test (e.g. /health)"),
    method: str = typer.Option("GET", "--method", "-m", help="HTTP method"),
    requests: int = typer.Option(100, "--requests", "-n", help="Total requests"),
    clients: int = typer.Option(
        10, "--clients", "-c", help="Concurrent in-flight requests"
    ),
    payload: str | None = typer.Option(
        None, "--payload", help="JSON payload as a string"
    ),
    payload_file: str | None = typer.Option(
        None, "--payload-file", help="Path to a JSON payload file"
    ),
    header: list[str] = typer.Option(
        [], "--header", "-H", help="Custom header KEY=VALUE (repeatable)"
    ),
    path_param: list[str] = typer.Option(
        [],
        "--path-param",
        "-p",
        help="Substitute {placeholders} in the path: KEY=VALUE (repeatable)",
    ),
    as_admin: bool = typer.Option(
        False,
        "--as-admin",
        help="Force admin auth (default auto-picks admin when "
        "ADMIN_USER_EMAILS is set, else a regular user)",
    ),
    as_user: bool = typer.Option(
        False,
        "--as-user",
        help="Force regular non-admin auth instead of the auto default",
    ),
    anon: bool = typer.Option(
        False,
        "--anon",
        help="Send unauthenticated requests; by default requests are "
        "auto-authenticated so auth-gated routes work without setup",
    ),
    base_url: str = typer.Option(
        "http://localhost:8000", "--base-url", help="Base URL for out-of-process runs"
    ),
    in_process: bool = typer.Option(
        False,
        "--in-process",
        help="Run via httpx.ASGITransport against the FastAPI app (no network)",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="Per-request timeout (s)"),
    delay_ms: int = typer.Option(
        0, "--delay-ms", help="Per-request throttle delay (ms)"
    ),
    json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run a load test against an endpoint."""
    headers = parse_headers(header)
    auth_as = apply_auto_auth(
        headers, as_admin=as_admin, as_user=as_user, anon=anon, quiet=json
    )
    path_params = parse_kv_flag(path_param, "--path-param")

    parsed_payload: dict | str | None = None
    if payload_file:
        with open(payload_file) as f:
            parsed_payload = json_lib.load(f)
    elif payload:
        parsed_payload = json_lib.loads(payload)

    config = APILoadTestConfiguration(
        method=method,
        path=path,
        requests=requests,
        clients=clients,
        payload=parsed_payload,
        headers=headers,
        auth_as=auth_as,
        path_params=path_params,
        base_url=base_url,
        in_process=in_process,
        timeout_s=timeout,
        delay_ms=delay_ms,
    )

    fastapi_app = _get_fastapi_app() if in_process else None

    # Progress bar: shown in interactive mode (TTY, not --json). Updated
    # via the service's progress_callback after each request finishes.
    progress: Progress | None = None
    task_id_handle = None
    show_progress = not json and sys.stdout.isatty()
    if show_progress:
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[dim]•[/dim]"),
            TimeElapsedColumn(),
            TextColumn("[dim]•[/dim]"),
            TimeRemainingColumn(),
            console=_progress_console(),
            transient=False,
        )
        progress.start()
        task_id_handle = progress.add_task(f"{method.upper()} {path}", total=requests)

    def _on_progress(done: int, total: int) -> None:
        if progress is None or task_id_handle is None:
            return
        progress.update(task_id_handle, completed=done, total=total)

    async def _do_run(store):
        service = APILoadTestService(store=store)
        return await service.run(
            config, app=fastapi_app, progress_callback=_on_progress
        )

    try:
        try:
            result = asyncio.run(_with_store(_do_run))
        finally:
            if progress is not None:
                progress.stop()
    except ValueError as exc:
        # The service raises ValueError up-front for misconfigured runs
        # (unsubstituted path params, etc.). Print the message verbatim
        # and exit non-zero rather than dumping a traceback. Use sys.exit
        # rather than typer.Exit because the project's CLI wrapper
        # (app/cli/main.py) runs ``standalone_mode=False`` and doesn't
        # always surface click-level exits as a process exit code.
        console.print(str(exc), style=theme.ERROR)
        sys.exit(2)

    if json:
        print(result.model_dump_json())
    else:
        _render_result(result)

    # Deliberately no exit-1 on ``tasks_failed > 0``. A run that observed
    # endpoint errors is data, not a test failure. Gate your CI on the
    # JSON output if you want to fail on a specific error rate.


@app.command()
def results(
    test_id: str = typer.Argument(..., help="Test ID returned by `run`"),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """Replay a previous test result by ID."""

    async def _do_get(store):
        service = APILoadTestService(store=store)
        return await service.get_result(test_id)

    result = asyncio.run(_with_store(_do_get))
    if result is None:
        console.print(f"No result found for test_id={test_id!r}", style=theme.ERROR)
        sys.exit(1)

    if json:
        print(result.model_dump_json())
    else:
        _render_result(result)


@app.command()
def recent(
    limit: int = typer.Option(10, "--limit", "-n", help="Max runs to show"),
    json: bool = typer.Option(False, "--json"),
) -> None:
    """List the most recent test runs (newest first)."""

    async def _do_list(store):
        service = APILoadTestService(store=store)
        return await service.list_recent(limit)

    items = asyncio.run(_with_store(_do_list))

    if json:
        print(json_lib.dumps([r.model_dump() for r in items]))
        return

    if not items:
        console.print("No recent test runs.")
        return

    table = Table(title=f"Recent test runs (up to {limit})")
    table.add_column("TEST ID")
    table.add_column("TARGET")
    table.add_column("REQ/S")
    table.add_column("P95 ms")
    table.add_column("ERROR %")
    table.add_column("WHEN")
    for r in items:
        target = f"{r.configuration.method} {r.configuration.path}"
        table.add_row(
            r.test_id,
            target,
            f"{r.metrics.overall_throughput:.1f}",
            f"{r.metrics.latency_ms_p95:.1f}",
            f"{r.metrics.failure_rate_percent:.1f}%",
            format_relative_time(r.start_time),
        )
    console.print(table)
