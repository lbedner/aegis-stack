"""Benchmark commands: how this app performs under a given configuration.

`api-load-test` answers "how much can this one route take". This answers
"how much does the configuration underneath it matter", which needs two
servers booted and driven identically. Separate group because the question
is different and because the answers are comparisons, not measurements.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Annotated
import urllib.error
import urllib.request

import typer

from app.cli import theme
from app.cli.api_load_test import parse_kv_flag
from app.cli.api_load_test_auth import apply_auto_auth

# Imported by name, not used through the module: ``_driver_fn`` returns
# these as globals of THIS module, which is where the tests patch them.
from app.cli.bench_drivers import (
    Sample,
    Target,
    _measure_ab,
    _measure_ab_docker,
    _measure_api_load_test,
    choose_driver,
    substitute_path_params,
)
from app.core.loops import ENGINE_LOOPS, resolve_loop
from app.i18n import lazy_t, t
from scripts.resolve_ports import _find_free_port

app = typer.Typer(name="bench", help=lazy_t("bench.help"))
console = theme.console()

ENGINES = ("uvicorn", "granian")
READY_TIMEOUT_S = 90.0


def _is_serving(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health/", timeout=2
        ) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError):
        return False


def _wait_until_ready(proc: subprocess.Popen[bytes], port: int, log: Path) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"server exited with code {proc.returncode} before serving:\n"
                f"{log.read_text()[-2000:]}"
            )
        if _is_serving(port):
            return
        time.sleep(0.5)
    raise TimeoutError(
        f"server was not serving within {READY_TIMEOUT_S}s:\n{log.read_text()[-2000:]}"
    )


@contextmanager
def _serving(engine: str, port: int, loop: str) -> Generator[None]:
    """Run the real entrypoint under one engine and one loop, reload off.

    ``loop`` is always concrete here. Resolving it before the child starts
    is what lets the report name the loop without reading it back out of a
    log, which would be silence the moment someone raises the log level.
    """
    env = {
        **os.environ,
        "WEBSERVER_ENGINE": engine,
        "WEBSERVER_LOOP": loop,
        "PORT": str(port),
        "AUTO_RELOAD": "false",
    }
    with tempfile.NamedTemporaryFile(suffix=f"-{engine}.log", delete=False) as handle:
        log = Path(handle.name)
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.entrypoints.webserver"],
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    try:
        _wait_until_ready(proc, port, log)
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.unlink(missing_ok=True)


def _row(engine: str, loop: str, sample: Sample) -> str:
    return (
        f"{engine:<10}{loop:<10}"
        f"{sample.throughput:>12,.0f}"
        f"{sample.p50_ms:>12.2f}"
        f"{sample.p95_ms:>12.2f}"
        f"{sample.p99_ms:>12.2f}"
        f"{sample.failed:>10}"
    )


def _resolve_target(
    method: str,
    path: str,
    path_param: list[str],
    header: list[str],
    payload: str | None,
    payload_file: str | None,
    as_admin: bool,
    as_user: bool,
    anon: bool,
) -> Target:
    headers = parse_kv_flag(header, "--header")
    apply_auto_auth(headers, as_admin=as_admin, as_user=as_user, anon=anon, quiet=True)
    body = Path(payload_file).read_text() if payload_file else payload
    return Target(
        method=method.upper(),
        path=substitute_path_params(path, parse_kv_flag(path_param, "--path-param")),
        headers=headers,
        payload=body,
    )


@app.command()
def engines(
    path: Annotated[
        str, typer.Option(help="Route to hit; `api-load-test list` shows them")
    ] = "/health/",
    method: Annotated[str, typer.Option(help="HTTP method")] = "GET",
    path_param: Annotated[
        list[str] | None, typer.Option(help="Fill a {placeholder}; repeatable")
    ] = None,
    header: Annotated[
        list[str] | None, typer.Option(help="KEY=VALUE; repeatable")
    ] = None,
    payload: Annotated[str | None, typer.Option(help="Body as a JSON string")] = None,
    payload_file: Annotated[str | None, typer.Option(help="Body from a file")] = None,
    as_admin: Annotated[bool, typer.Option("--as-admin")] = False,
    as_user: Annotated[bool, typer.Option("--as-user")] = False,
    anon: Annotated[bool, typer.Option("--anon")] = False,
    requests: Annotated[int, typer.Option("--requests", "-n")] = 2000,
    clients: Annotated[int, typer.Option("--clients", "-c")] = 50,
    rounds: Annotated[int, typer.Option(help="Runs per engine; best is kept")] = 2,
    loop: Annotated[
        list[str] | None,
        typer.Option(help="Event loop to pin; repeat to sweep the matrix"),
    ] = None,
    driver: Annotated[
        str, typer.Option(help="auto | ab | ab-docker | api-load-test")
    ] = "auto",
) -> None:
    """Compare the ASGI engines on one of this app's routes."""
    if sum((as_admin, as_user, anon)) > 1:
        console.print(t("bench.auth.one_only"), style=theme.ERROR)
        raise typer.Exit(2)

    try:
        target = _resolve_target(
            method,
            path,
            path_param or [],
            header or [],
            payload,
            payload_file,
            as_admin,
            as_user,
            anon,
        )
    except (ValueError, OSError) as exc:
        console.print(str(exc), style=theme.ERROR)
        raise typer.Exit(2) from exc

    chosen_driver, reason = choose_driver(driver, target.method)
    if reason:
        console.print(t("bench.driver.fallback", driver=chosen_driver, reason=reason))
    measure = _driver_fn(chosen_driver)

    # The same rule the entrypoint uses, so the report states the loop
    # rather than inferring it. Resolved per choice: one unusable loop
    # (zuvloop below 3.14) drops out of the sweep instead of ending it.
    pinned_loops: list[str] = []
    for choice in loop or ["auto"]:
        try:
            resolved = resolve_loop(choice)
        except ValueError as exc:
            console.print(str(exc), style=theme.ERROR)
            continue
        if resolved not in pinned_loops:
            pinned_loops.append(resolved)
    if not pinned_loops:
        raise typer.Exit(2)

    best: dict[tuple[str, str], Sample] = {}
    for pinned in pinned_loops:
        for engine in ENGINES:
            # A loop only one engine can run is a normal thing to sweep, so
            # skip the other rather than dying halfway through the matrix.
            if pinned not in ENGINE_LOOPS[engine]:
                console.print(t("bench.skip", engine=engine, loop=pinned))
                continue
            port = _find_free_port(8400)
            console.print(t("bench.running", engine=engine, loop=pinned, port=port))
            with _serving(engine, port, pinned):
                for _ in range(rounds):
                    sample = measure(port, target, requests, clients)
                    current = best.get((engine, pinned))
                    if current is None or sample.throughput > current.throughput:
                        best[(engine, pinned)] = sample

    _report(best, target, requests, clients, rounds, chosen_driver)


def _driver_fn(driver: str) -> Callable[[int, Target, int, int], Sample]:
    """Resolve the driver by name, at call time.

    A module-level dict would capture these at import, which quietly
    breaks both patching and any later reassignment.
    """
    if driver == "ab":
        return _measure_ab
    if driver == "ab-docker":
        return _measure_ab_docker
    return _measure_api_load_test


def _report(
    best: dict[tuple[str, str], Sample],
    target: Target,
    requests: int,
    clients: int,
    rounds: int,
    driver: str,
) -> None:
    console.print()
    console.print(
        t(
            "bench.summary",
            requests=requests,
            clients=clients,
            rounds=rounds,
            target=target.label,
            driver=driver,
        )
    )
    console.print()
    header_row = (
        f"{'engine':<10}{'loop':<10}{'req/s':>12}{'p50 ms':>12}"
        f"{'p95 ms':>12}{'p99 ms':>12}{'failed':>10}"
    )
    console.print(header_row, style=theme.ACCENT)
    console.print("-" * len(header_row))
    # Engine-major, so the rows read as "this engine, across its loops".
    for engine in ENGINES:
        for (row_engine, row_loop), sample in best.items():
            if row_engine == engine:
                console.print(_row(engine, row_loop, sample))

    throughputs = {pair: sample.throughput for pair, sample in best.items()}
    if len(throughputs) < 2:
        console.print()
        console.print(t("bench.one_engine"))
        return
    # Best and worst of the whole matrix, which is the comparison the
    # sweep exists to make - it may be two loops on one engine.
    winner = max(throughputs, key=lambda pair: throughputs[pair])
    loser = min(throughputs, key=lambda pair: throughputs[pair])
    if throughputs[loser]:
        console.print()
        console.print(
            t(
                "bench.ratio",
                winner=f"{winner[0]}/{winner[1]}",
                ratio=f"{throughputs[winner] / throughputs[loser]:.2f}",
                loser=f"{loser[0]}/{loser[1]}",
            )
        )
    console.print(t("bench.noise"))
    if driver == "api-load-test":
        console.print(t("bench.driver.warning"))
