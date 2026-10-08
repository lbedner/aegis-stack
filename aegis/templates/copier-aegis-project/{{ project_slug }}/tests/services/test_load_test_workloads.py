"""The CPU load-test workload runs off the worker's event loop.

Every worker backend runs async tasks on one event loop per process, and
the loop also runs the claim keep-alive, heartbeats and runtime reports, so
the CPU work goes through ``cpu_bound`` (its behaviour is tested in
``tests/test_concurrency.py``).
"""

import asyncio
from typing import Any

import pytest

from app.services import load_test_workloads


def test_the_cpu_workload_runs_through_cpu_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    async def cpu_bound(fn: Any, *args: Any) -> dict[str, str]:
        seen.append(fn)
        return {"status": "completed"}

    monkeypatch.setattr(load_test_workloads, "cpu_bound", cpu_bound)

    assert asyncio.run(load_test_workloads.run_cpu_intensive())["status"] == "completed"
    assert seen == [load_test_workloads._cpu_work]
