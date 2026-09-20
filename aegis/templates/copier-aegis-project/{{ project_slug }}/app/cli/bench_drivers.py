"""How a benchmark actually measures: the drivers, and the shapes they return.

Split from ``bench`` so the command module is the experiment - boot two
servers, sweep the axes, print the comparison - and this is the ruler.
``bench`` imports these names back into its own namespace, because
``_driver_fn`` resolves them at call time and the tests patch them there.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import NamedTuple

from app.cli import theme
from app.i18n import t

console = theme.console()

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
