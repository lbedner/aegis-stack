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

import asyncio
import json as json_lib
import sys
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

import typer
from app.cli import theme
from app.core.formatting import format_relative_time
from app.services.load_test.api.discovery import list_routes
from app.services.load_test.api.models import (
    APILoadTestConfiguration,
    APILoadTestResult,
)
from app.services.load_test.api.service import APILoadTestService
from app.services.load_test.common.storage import RedisResultStore
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

if TYPE_CHECKING:
    from fastapi import FastAPI

app = typer.Typer(
    name="api-load-test",
    help="Run load tests against any endpoint in this project's FastAPI app.",
    no_args_is_help=True,
)

console = theme.console()



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


def _get_fastapi_app() -> "FastAPI":
    """Lazily import + construct the project's FastAPI app.

    Kept as a separate function so tests can mock it without booting the
    real integrated app (which would trigger lifespan, DB connections,
    etc.).
    """
    from app.integrations.main import create_integrated_app

    return create_integrated_app()


def _build_redis_client() -> Any | None:
    """Construct a redis.asyncio client from project config; ``None`` if
    Redis isn't configured/available."""
    try:
        import redis.asyncio as aioredis
        from app.core.config import settings

        redis_url = getattr(settings, "redis_url_effective", None)
        if not redis_url:
            return None
        return aioredis.from_url(redis_url)
    except Exception:
        return None


def _make_store() -> RedisResultStore[APILoadTestResult] | None:
    """Construct a Redis-backed store; ``None`` if Redis isn't available.

    Mockable seam: tests patch this (or the service class) to skip the
    storage path entirely. The redis client is owned by ``_with_store``,
    not by the store itself, so it can be closed cleanly at the end of
    the operation.
    """
    client = _build_redis_client()
    if client is None:
        return None
    return RedisResultStore(
        redis=client,
        key_prefix="api_load_test",
        result_model=APILoadTestResult,
    )


T = TypeVar("T")


async def _with_store(
    op: Callable[[RedisResultStore[APILoadTestResult] | None], Awaitable[T]],
) -> T:
    """Run ``op`` with a store, ensuring the underlying redis client is
    closed cleanly inside the event loop.

    Without this, the redis client's ``__del__`` fires during interpreter
    shutdown when the asyncio loop has already closed, producing an ugly
    ``RuntimeError: Event loop is closed`` traceback.
    """
    store = _make_store()
    try:
        return await op(store)
    finally:
        if store is not None:
            await store.aclose()


def _parse_kv_flag(items: list[str], flag_name: str) -> dict[str, str]:
    """Parse repeated ``KEY=VALUE`` flags (``--header``, ``--path-param``).

    Centralized so the error message points at the actual flag the user
    typed.
    """
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise typer.BadParameter(
                f"{flag_name} must be KEY=VALUE, got: {item!r}"
            )
        key, _, value = item.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def _parse_headers(items: list[str]) -> dict[str, str]:
    return _parse_kv_flag(items, "--header")


def _get_auth_dependency() -> object | None:
    """Return the project's auth dependency callable, or ``None`` if the
    auth service isn't installed in this stack. Used to populate the
    ``AUTH`` column in ``list``."""
    try:
        from app.services.auth.deps import get_current_active_user

        return get_current_active_user
    except ImportError:
        return None


_LOAD_TEST_USER_EMAIL = "loadtest@example.com"


def _apply_auto_auth(
    headers: dict[str, str],
    *,
    as_admin: bool,
    as_user: bool,
    anon: bool,
    quiet: bool,
) -> str | None:
    """Inject a bearer token into ``headers`` so auth-gated routes work
    without manual login, and return the role used (for the result record).

    Auth is automatic by default: ``admin`` when ``ADMIN_USER_EMAILS`` is
    configured (so it clears ``require_admin``), otherwise a regular user,
    otherwise anonymous when the auth service isn't installed. ``--anon``
    disables it; ``--as-admin`` / ``--as-user`` force a role. An explicit
    ``--header Authorization`` always wins and is never overwritten. The token
    is signed with the project ``SECRET_KEY`` and the user lives in the project
    DB, so it validates against in-process and locally running servers sharing
    this ``.env``.
    """
    if sum((as_admin, as_user, anon)) > 1:
        console.print(
            "Pass only one of --as-admin / --as-user / --anon.", style=theme.ERROR
        )
        sys.exit(2)
    if anon or any(k.lower() == "authorization" for k in headers):
        return None

    try:
        from app.core.config import settings
        from app.core.security import create_access_token
    except ImportError:
        if as_admin or as_user:
            console.print(
                "Auth is not installed in this stack; --as-admin/--as-user "
                "are unavailable.",
                style=theme.ERROR,
            )
            sys.exit(2)
        return None

    has_allowlist = bool(settings.ADMIN_USER_EMAILS)
    if as_admin and not has_allowlist:
        console.print(
            "--as-admin needs ADMIN_USER_EMAILS set in .env, e.g. "
            'ADMIN_USER_EMAILS=["you@example.com"].',
            style=theme.ERROR,
        )
        sys.exit(2)

    use_admin = as_admin or (not as_user and has_allowlist)
    email = settings.ADMIN_USER_EMAILS[0] if use_admin else _LOAD_TEST_USER_EMAIL
    role = "admin" if use_admin else "user"

    asyncio.run(_ensure_active_verified_user(email))
    headers["Authorization"] = f"Bearer {create_access_token({'sub': email})}"
    if not quiet:
        theme.label(f"Authenticating as {role} ({email}); pass --anon to disable")
    return role


async def _ensure_active_verified_user(email: str) -> None:
    """Create the load-test user if absent, and ensure it is active and
    verified so it satisfies ``get_current_active_user`` and ``require_admin``.
    """
    import secrets

    from app.core.db import get_async_session
    from app.models.user import UserCreate
    from app.services.auth.users import UserService

    async with get_async_session() as session:
        user_service = UserService(session)
        user = await user_service.get_user_by_email(email)
        if user is None:
            user = await user_service.create_user(
                UserCreate(
                    email=email,
                    full_name="Load Test",
                    password=secrets.token_urlsafe(16),
                )
            )
        user.is_active = True
        user.is_verified = True
        session.add(user)
        await session.commit()


# The HTTP method is metadata in the route listing, not a state, so it
# renders dim (annotation) rather than carrying its own hue.
_METHOD_COLORS_CLI: dict[str, str] = {
    "GET": "dim",
    "POST": "dim",
    "PUT": "dim",
    "PATCH": "dim",
    "DELETE": "dim",
}


def _method_color(method: str) -> str:
    return _METHOD_COLORS_CLI.get(method, "dim")


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
    headers = _parse_headers(header)
    auth_as = _apply_auto_auth(
        headers, as_admin=as_admin, as_user=as_user, anon=anon, quiet=json
    )
    path_params = _parse_kv_flag(path_param, "--path-param")

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
        task_id_handle = progress.add_task(
            f"{method.upper()} {path}", total=requests
        )

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
                theme.ACCENT if 200 <= status < 400
                else theme.WARNING if 400 <= status < 500
                else theme.ERROR
            )
            console.print(f"  [{color}]{status}[/{color}]    {count}")
