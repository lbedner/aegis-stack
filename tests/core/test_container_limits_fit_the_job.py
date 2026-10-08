"""The process a person waits on is never the most throttled one.

A compose ``cpus`` limit is a freeze, not a slowdown: the kernel stops the
process once its share of each 100ms period is spent. The webserver is the
only interactive process in a generated stack and a single event loop -
every page, every htmx fragment, the Overseer and every streamed token run
on it - so a ceiling it hits shows up as the whole app stalling at once.
Measured on a running stack at ``cpus: '0.5'``: throttled in 11.8% of
periods, 83 seconds frozen, while ``worker-system`` at 1.0 stalled 6 times.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
# Everything that runs in the background rather than for a waiting person.
BACKGROUND = ("scheduler", "worker-system", "worker-load-test")
DEFAULT = re.compile(r"\$\{[A-Z_]+:-([0-9.]+)\}")
ANY_DEFAULT = re.compile(r"\$\{[A-Z_]+:-([^}]+)\}")
# Measured on a running taskiq worker (PSS): the supervisor, forkserver and
# resource tracker cost about 90 MiB once per container, and each worker
# process about 95 MiB, almost all of it its own.
FIXED_MIB = 90
PER_PROCESS_MIB = 95
WORKERS = ("worker-system", "worker-load-test")


def _compose(**overrides: Any) -> dict[str, Any]:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_worker": True,
        "include_scheduler": True,
        "include_redis": True,
        **overrides,
    }
    rendered = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/docker-compose.yml.jinja"
    ).render(context)
    return yaml.safe_load(rendered)


def _cpus(service: dict[str, Any]) -> float:
    """The limit a stack gets when nothing overrides it."""
    raw = str(service["deploy"]["resources"]["limits"]["cpus"])
    match = DEFAULT.search(raw)
    return float(match.group(1) if match else raw)


def _check(compose: dict[str, Any]) -> None:
    services = compose["services"]
    webserver = _cpus(services["webserver"])
    for name in BACKGROUND:
        if name in services:
            assert _cpus(services[name]) <= webserver, (
                f"{name} may use more CPU than the webserver a person is "
                f"waiting on ({_cpus(services[name])} > {webserver})"
            )


def test_no_background_container_outranks_the_webserver() -> None:
    _check(_compose())


def test_nor_with_finance_sizing_the_system_worker_up() -> None:
    _check(_compose(include_finance=True, include_database=True))


def test_the_webserver_limit_can_be_raised_without_editing_compose() -> None:
    raw = str(
        _compose()["services"]["webserver"]["deploy"]["resources"]["limits"]["cpus"]
    )
    assert DEFAULT.search(raw), f"webserver cpus is hardcoded: {raw!r}"


def _given(raw: object) -> str:
    """A compose value as a stack gets it when nothing overrides it."""
    match = ANY_DEFAULT.search(str(raw))
    return match.group(1) if match else str(raw)


def _processes(service: dict[str, Any]) -> int:
    for item in service.get("environment", []):
        name, _, value = str(item).partition("=")
        if name == "WORKER_PROCESSES":
            return int(_given(value))
    return 1  # arq: one process per container


def _memory_mib(service: dict[str, Any]) -> int:
    raw = _given(service["deploy"]["resources"]["limits"]["memory"])
    return int(raw[:-1]) * {"M": 1, "G": 1024}[raw[-1].upper()]


@pytest.mark.parametrize("backend", ["arq", "taskiq", "dramatiq"])
@pytest.mark.parametrize("finance", [False, True])
def test_a_workers_processes_fit_its_memory(backend: str, finance: bool) -> None:
    """Outside dev a worker starts every process it is told to, each about
    95 MiB on top of what the container costs once: past the limit the
    kernel kills it as it fills up, and ``restart`` makes that a loop."""
    overrides: dict[str, Any] = {"worker_backend": backend}
    if finance:
        overrides |= {"include_finance": True, "include_database": True}
    services = _compose(**overrides)["services"]
    for name in WORKERS:
        if name not in services:
            continue
        processes = _processes(services[name])
        need = FIXED_MIB + PER_PROCESS_MIB * processes
        assert need <= _memory_mib(services[name]), (
            f"{name}: {processes} processes need about {need} MiB, "
            f"over its {_memory_mib(services[name])} MiB limit"
        )
