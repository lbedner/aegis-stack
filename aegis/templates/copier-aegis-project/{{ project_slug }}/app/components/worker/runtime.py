"""What each worker process runs with, checked against the settings.

Every engine gets its concurrency from ``Settings.WORKER_QUEUES`` (taskiq's
max async tasks, dramatiq's threads, arq's ``max_jobs``). The web process
cannot see a worker's command line, and each engine has its own defaults,
so every worker writes a small report to Redis on startup - what it runs
with next to what the settings ask for - refreshed while it lives and
expiring when it dies. The Overseer's Runtime section reads it.

Run as ``python -m app.components.worker.runtime concurrency <queue>`` it
checks the settings against the discovered queues (refusing to go on if
``WORKER_QUEUES`` names one that does not exist) and prints that queue's
concurrency, which the entrypoint hands to taskiq and dramatiq.
"""

import asyncio
from collections.abc import Iterable
import contextlib
from importlib import metadata
import os
import sys
from typing import Any

from app.core.config import settings
from app.core.log import logger
from app.core.queue_workers import concurrency_for
from app.core.key_family import KeyFamily

RUNTIME_KEY_PREFIX = "worker:"
RUNTIME_KEY_SUFFIX = ":runtime"
RUNTIME_TTL_SECONDS = 60
RUNTIME_REFRESH_SECONDS = 20

# Each engine's command-line flags for processes and per-process
# concurrency, and its defaults when a flag is left out. arq has neither:
# one process, ``max_jobs`` from its WorkerSettings.
ENGINE_FLAGS: dict[str, dict[str, str]] = {
    "taskiq": {
        "--workers": "processes",
        "-w": "processes",
        "--max-async-tasks": "concurrency",
    },
    "dramatiq": {
        "--processes": "processes",
        "-p": "processes",
        "--threads": "concurrency",
        "-t": "concurrency",
    },
}
ENGINE_DEFAULTS: dict[str, dict[str, int]] = {
    "taskiq": {"processes": 2, "concurrency": 100},
    "dramatiq": {"processes": os.cpu_count() or 1, "concurrency": 8},
}

REDIS_KEYS = (
    KeyFamily(
        f"{RUNTIME_KEY_PREFIX}*{RUNTIME_KEY_SUFFIX}",
        "hash",
        "Worker runtime",
        "What each worker process runs with, refreshed while it lives",
        "Worker runtime",
        columns=("Setting", "Value"),
    ),
)


def runtime_key(worker: str) -> str:
    return f"{RUNTIME_KEY_PREFIX}{worker}{RUNTIME_KEY_SUFFIX}"


def launch_settings(engine: str, argv: list[str]) -> dict[str, int]:
    """Processes and per-process concurrency from an engine's command line,
    with the engine's defaults for any flag it leaves out."""
    flags = ENGINE_FLAGS[engine]
    found = dict(ENGINE_DEFAULTS[engine])
    for i, arg in enumerate(argv):
        flag, _, inline = arg.partition("=")
        name = flags.get(flag)
        value = inline or (argv[i + 1] if i + 1 < len(argv) else "")
        if name and value.isdigit():
            found[name] = int(value)
    return found


def configured(queue: str) -> tuple[int, str]:
    """The concurrency the settings ask for on ``queue``, and which setting."""
    source = (
        f"WORKER_QUEUES[{queue}]"
        if queue in settings.WORKER_QUEUES
        else "WORKER_QUEUE_DEFAULT"
    )
    return concurrency_for(queue), source


def unknown_queues(names: Iterable[str], discovered: Iterable[str]) -> list[str]:
    """Configured queue names that match no queue."""
    known = set(discovered)
    return sorted(name for name in names if name not in known)


def check_queues() -> None:
    """Refuse to go on if ``WORKER_QUEUES`` names a queue that does not
    exist: a typo there would otherwise quietly leave the default in force."""
    from app.components.worker.registry import discover_worker_queues

    discovered = discover_worker_queues()
    bad = unknown_queues(settings.WORKER_QUEUES, discovered)
    if bad:
        raise SystemExit(
            f"WORKER_QUEUES names queues that do not exist: {', '.join(bad)} "
            f"(queues: {', '.join(sorted(discovered))})"
        )


def report(
    *,
    worker: str,
    queue: str,
    engine: str,
    version: str,
    processes: int,
    concurrency: int,
) -> dict[str, Any]:
    """One worker's report: what it runs with, and what the settings ask."""
    asked, source = configured(queue)
    return {
        "worker": worker,
        "queue": queue,
        "engine": engine,
        "version": version,
        "processes": processes,
        "concurrency": concurrency,
        "configured": asked,
        "source": source,
    }


async def publish_runtime(redis: Any, fields: dict[str, Any]) -> None:
    """Write (or refresh) a report. Best effort: it must never stop a worker."""
    key = runtime_key(str(fields.get("worker")))
    try:
        await redis.hset(key, mapping=fields)
        await redis.expire(key, RUNTIME_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - monitoring must not break work
        logger.debug(f"Worker runtime report failed: {exc}")


def publish_runtime_sync(redis: Any, fields: dict[str, Any]) -> None:
    """``publish_runtime`` for engines whose hooks are synchronous (dramatiq)."""
    key = runtime_key(str(fields.get("worker")))
    try:
        redis.hset(key, mapping=fields)
        redis.expire(key, RUNTIME_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - monitoring must not break work
        logger.debug(f"Worker runtime report failed: {exc}")


async def keep_reporting(redis: Any, fields: dict[str, Any]) -> None:
    """Publish now, then refresh every ``RUNTIME_REFRESH_SECONDS`` until
    cancelled, so a dead worker's report expires on its own."""
    while True:
        await publish_runtime(redis, fields)
        await asyncio.sleep(RUNTIME_REFRESH_SECONDS)


def start_reporting(redis: Any, fields: dict[str, Any]) -> asyncio.Task[None]:
    """``keep_reporting`` as a background task; cancel it on shutdown."""
    return asyncio.create_task(keep_reporting(redis, fields))


async def stop_reporting(
    redis: Any, task: asyncio.Task[None] | None, worker: str
) -> None:
    """Stop refreshing and remove the report: a clean stop leaves no trace."""
    if task is not None:
        task.cancel()
    with contextlib.suppress(Exception):
        await redis.delete(runtime_key(worker))


def engine_version(package: str) -> str:
    """The installed version of a worker engine, or "" if unknown."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return ""


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def read_runtime(redis: Any) -> list[dict[str, str]]:
    """Every live worker's report, by queue then worker."""
    reports = []
    async for key in redis.scan_iter(match=runtime_key("*"), count=100):
        fields = await redis.hgetall(key)
        reports.append({_text(k): _text(v) for k, v in fields.items()})
    return sorted(reports, key=lambda r: (r.get("queue", ""), r.get("worker", "")))


if __name__ == "__main__":
    if sys.argv[1:2] == ["concurrency"] and len(sys.argv) == 3:
        check_queues()
        print(configured(sys.argv[2])[0])
    else:
        sys.exit("usage: python -m app.components.worker.runtime concurrency <queue>")
