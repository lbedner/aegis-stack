"""Benchmark commands: how this app performs under a given configuration.

`api-load-test` answers "how much can this one route take". This answers
"how much does the configuration underneath it matter", which needs two
servers booted and driven identically. Separate group because the question
is different and because the answers are comparisons, not measurements.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Annotated, NamedTuple
import urllib.error
import urllib.request

import typer

from app.cli import theme
from app.cli.api_load_test import apply_auto_auth, parse_kv_flag
from app.core.loops import ENGINE_LOOPS, resolve_loop
from app.i18n import lazy_t, t
from scripts.resolve_ports import _find_free_port

app = typer.Typer(name="bench", help=lazy_t("bench.help"))
console = theme.console()

ENGINES = ("uvicorn", "granian")
READY_TIMEOUT_S = 90.0
# ApacheBench: ships with macOS, `apt install apache2-utils` on Debian.
AB = shutil.which("ab") or "/usr/sbin/ab"
# Official Apache image; ab lives on its PATH. Used when the host has
# no ab of its own, which is most Linux.
DOCKER_AB_IMAGE = "httpd:alpine"
# ab can issue these; anything else has to go through the Python driver.
AB_METHODS = {"GET": None, "POST": "-p", "PUT": "-u"}


class Target(NamedTuple):
    """The route under test, resolved and ready to hit."""

    method: str
    path: str
    headers: dict[str, str]
    payload: str | None

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


class Sample(NamedTuple):
    throughput: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    failed: int


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


def substitute_path_params(path: str, params: dict[str, str]) -> str:
    """Fill ``{name}`` placeholders, refusing to benchmark a template.

    An unsubstituted placeholder does not 404 cleanly: it becomes a URL
    with a literal brace in it, and the run reports fast, uniform 404s
    that look like a real result.
    """
    filled = path
    for key, value in params.items():
        filled = filled.replace("{" + key + "}", value)
    if missing := re.findall(r"\{([^}/]+)\}", filled):
        raise ValueError(
            f"unsubstituted path params in {path!r}: {', '.join(missing)}. "
            f"Pass --path-param {missing[0]}=<value>."
        )
    return filled


def parse_ab(stdout: str) -> Sample:
    """Pull the numbers out of an ApacheBench report.

    Separate from the subprocess call so it can be tested without running
    a server: a silently broken pattern here would report zeros, which
    reads like a real result.
    """
    numbers: dict[str, float] = {}
    for line in stdout.splitlines():
        if match := re.match(r"Requests per second:\s+([\d.]+)", line):
            numbers["throughput"] = float(match.group(1))
        elif match := re.match(r"Failed requests:\s+(\d+)", line):
            numbers["failed"] = float(match.group(1))
        elif match := re.match(r"\s+(50|95|99)%\s+(\d+)", line):
            numbers[f"p{match.group(1)}"] = float(match.group(2))
    if "throughput" not in numbers:
        raise ValueError(f"no throughput line in ab output:\n{stdout[:500]}")
    return Sample(
        throughput=numbers["throughput"],
        p50_ms=numbers.get("p50", 0.0),
        p95_ms=numbers.get("p95", 0.0),
        p99_ms=numbers.get("p99", 0.0),
        failed=int(numbers.get("failed", 0)),
    )


def _ab_flags(
    target: Target, requests: int, clients: int, body: str | None
) -> list[str]:
    """The ab flags both drivers share. ``body`` is a path inside whichever
    filesystem the binary will read."""
    # -q quiets the per-150-request progress counter; percentiles stay.
    flags = ["-n", str(requests), "-c", str(clients), "-q"]
    for key, value in target.headers.items():
        flags += ["-H", f"{key}: {value}"]
    if (method_flag := AB_METHODS[target.method]) and body:
        flags += [method_flag, body, "-T", "application/json"]
    return flags


@contextmanager
def _body_file(target: Target) -> Generator[Path | None]:
    """A temp file holding the request body, when the method needs one."""
    if not AB_METHODS[target.method]:
        yield None
        return
    with tempfile.NamedTemporaryFile("w", suffix=".body", delete=False) as handle:
        handle.write(target.payload or "")
        path = Path(handle.name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _measure_ab(port: int, target: Target, requests: int, clients: int) -> Sample:
    """Drive with ApacheBench, which can actually saturate these servers."""
    with _body_file(target) as body:
        flags = _ab_flags(target, requests, clients, str(body) if body else None)
        completed = subprocess.run(
            [AB, *flags, f"http://127.0.0.1:{port}{target.path}"],
            capture_output=True,
            text=True,
            check=True,
        )
    return parse_ab(completed.stdout)


def _measure_ab_docker(
    port: int, target: Target, requests: int, clients: int
) -> Sample:
    """The same ab, out of the official httpd image.

    ab is bundled on macOS and absent on most Linux, which is CI, most
    containers, and plenty of laptops. Docker is already a hard
    requirement for a generated project, so the tool that says "go
    measure your own routes" should not be the one thing that needs a
    system package first.

    ``host.docker.internal`` plus the host-gateway alias reaches the
    server on the host from both Docker Desktop and Linux.
    """
    # Linux gets the host's own network stack, with no NAT between the
    # container and the server, so it should measure close to a local ab.
    # Unverified: written on macOS, where Docker NATs through a VM. That
    # path IS measured, and it throttles absolute throughput several times
    # over while leaving the ratio between engines intact (1.53x against
    # 1.54x native). Either way, do not compare a container number to a
    # native one.
    if sys.platform == "linux":
        network, host = ["--network", "host"], "127.0.0.1"
    else:
        network = ["--add-host=host.docker.internal:host-gateway"]
        host = "host.docker.internal"

    with _body_file(target) as body:
        mount = ["-v", f"{body}:/tmp/body:ro"] if body else []
        flags = _ab_flags(target, requests, clients, "/tmp/body" if body else None)
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                *network,
                *mount,
                DOCKER_AB_IMAGE,
                "ab",
                *flags,
                f"http://{host}:{port}{target.path}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    return parse_ab(completed.stdout)


def _measure_api_load_test(
    port: int, target: Target, requests: int, clients: int
) -> Sample:
    """Drive with the project's own load tester.

    Honest health warning: this client is asyncio + httpx, and on these
    endpoints it tops out around 500 req/s - well under what either engine
    can serve - so it measures the client, not the server, and reports the
    two engines as equal. It is the fallback for routes ab cannot issue,
    and when ab is not installed.
    """
    argv = [
        sys.executable,
        "-m",
        "app.cli.main",
        "api-load-test",
        "run",
        target.path,
        "--method",
        target.method,
        "--requests",
        str(requests),
        "--clients",
        str(clients),
        "--base-url",
        f"http://127.0.0.1:{port}",
        "--json",
    ]
    for key, value in target.headers.items():
        argv += ["--header", f"{key}={value}"]
    if target.payload:
        argv += ["--payload", target.payload]

    completed = subprocess.run(argv, capture_output=True, text=True, check=True)
    # The CLI may log before the payload; the JSON document is the last line.
    metrics = json.loads(completed.stdout.strip().splitlines()[-1])["metrics"]
    return Sample(
        throughput=metrics["overall_throughput"],
        p50_ms=metrics["latency_ms_p50"],
        p95_ms=metrics["latency_ms_p95"],
        p99_ms=metrics["latency_ms_p99"],
        failed=metrics["tasks_failed"],
    )


def _row(engine: str, loop: str, sample: Sample) -> str:
    return (
        f"{engine:<10}{loop:<10}"
        f"{sample.throughput:>12,.0f}"
        f"{sample.p50_ms:>12.2f}"
        f"{sample.p95_ms:>12.2f}"
        f"{sample.p99_ms:>12.2f}"
        f"{sample.failed:>10}"
    )


def choose_driver(requested: str, method: str) -> tuple[str, str | None]:
    """Pick the load generator, and say why when it is not the fast one.

    Order matters: a local ab beats a containerized one on startup cost,
    and both beat the Python client, which cannot saturate either engine
    and so reports them as equal.
    """
    if requested in {"api-load-test", "ab", "ab-docker"}:
        return requested, None
    if method not in AB_METHODS:
        return "api-load-test", t("bench.driver.method", method=method)
    if Path(AB).exists():
        return "ab", None
    if shutil.which("docker"):
        return "ab-docker", t("bench.driver.docker")
    return "api-load-test", t("bench.driver.missing")


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
    loop: Annotated[str, typer.Option(help="Event loop to pin")] = "auto",
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

    # The same rule the entrypoint uses, called once so the report states
    # the loop rather than inferring it.
    pinned = resolve_loop(loop)

    best: dict[str, Sample] = {}
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
                current = best.get(engine)
                if current is None or sample.throughput > current.throughput:
                    best[engine] = sample

    _report(best, pinned, target, requests, clients, rounds, chosen_driver)


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
    best: dict[str, Sample],
    loop: str,
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
    for engine in ENGINES:
        if engine in best:
            console.print(_row(engine, loop, best[engine]))

    throughputs = {engine: sample.throughput for engine, sample in best.items()}
    if len(throughputs) < 2:
        console.print()
        console.print(t("bench.one_engine"))
        return
    winner = max(throughputs, key=lambda engine: throughputs[engine])
    loser = min(throughputs, key=lambda engine: throughputs[engine])
    if throughputs[loser]:
        console.print()
        console.print(
            t(
                "bench.ratio",
                winner=winner,
                ratio=f"{throughputs[winner] / throughputs[loser]:.2f}",
                loser=loser,
            )
        )
    console.print(t("bench.noise"))
    if driver == "api-load-test":
        console.print(t("bench.driver.warning"))
