"""What each service costs in memory to load, held to a budget.

A service's dependencies (a provider SDK, a PDF library, an embedding model
pulling in torch) add to every process that loads it, and a review cannot
see that. Each installed service's whole package is imported in a fresh
interpreter on top of what every process loads anyway (config, logging),
and the memory it adds is held to the budget below: over it fails, naming
the service and by how much.

The budget is a ratchet. It records what each service costs today, with
room for noise between machines; raise a service's entry in the same
change that adds the weight, on purpose, and lower it when a change makes
the service lighter.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path
import subprocess
import sys

import pytest

import app.services

# Megabytes each service this project ships adds when all of its modules
# are loaded.
BUDGET_MB = {
    "ai": 140,
    "auth": 50,
    "backend": 10,
    "blog": 40,
    "change_queue": 50,
    "comms": 25,
    "documents": 100,
    "finance": 85,
    "insights": 40,
    "load_test": 25,
    "ops": 10,
    "payment": 55,
    "rag": 75,
    "research": 50,
    "scheduler": 35,
    "shared": 50,
    "system": 45,
}
# Allowed over budget before it fails: the larger of these. Memory varies a
# few megabytes by platform and Python version.
TOLERANCE_MB = 15
TOLERANCE_SHARE = 0.25

_MEASURE = """
import importlib, pkgutil, resource, sys

def rss():
    used = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return used / 1024 / 1024 if sys.platform == "darwin" else used / 1024

import app.core.config, app.core.log
base = rss()
package = importlib.import_module("app.services." + sys.argv[1])
for found in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
    importlib.import_module(found.name)
print(rss() - base)
"""


def _installed() -> list[str]:
    """Each service package in this stack that holds any code."""
    root = Path(app.services.__file__).parent
    return sorted(
        d.name
        for d in root.iterdir()
        if (d / "__init__.py").exists()
        and any(p.stat().st_size for p in d.rglob("*.py") if p.name != "__init__.py")
    )


def _measure(service: str) -> float:
    done = subprocess.run(
        [sys.executable, "-c", _MEASURE, service],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, f"{service} does not import: {done.stderr[-2000:]}"
    return float(done.stdout.strip().splitlines()[-1])


@cache
def _costs() -> dict[str, float]:
    """Every installed service's cost, measured side by side."""
    services = _installed()
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(services, pool.map(_measure, services), strict=True))


@pytest.mark.parametrize("service", _installed())
def test_a_service_stays_within_its_memory_budget(service: str) -> None:
    cost = _costs()[service]
    if service not in BUDGET_MB:
        # A plugin's service: its own package keeps its own budget.
        pytest.skip(f"{service} has no budget here ({cost:.0f} MB today)")
    budget = BUDGET_MB[service]
    limit = budget + max(TOLERANCE_MB, budget * TOLERANCE_SHARE)
    assert cost <= limit, (
        f"{service} adds {cost:.0f} MB when loaded, over its {budget} MB budget"
        f" (limit {limit:.0f} MB): find what grew, or raise the budget on purpose"
    )
