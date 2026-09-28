"""Redis must never evict the worker's queue to make room.

Redis holds the job streams, the pause flag and the task-history indexes
next to the cache, in one server. ``allkeys-*`` eviction picks any key
under memory pressure, so a busy stack silently loses queued jobs: nothing
errors, the work just never runs. ``volatile-*`` only evicts keys that
already expire (cache entries, job results, task records), and once none
are left Redis refuses the write instead of dropping data.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SOURCES = [
    ROOT
    / "aegis/templates/copier-aegis-project/{{ project_slug }}/docker-compose.yml.jinja",
    *sorted((ROOT / "docs").rglob("*.md")),
]
_POLICY = re.compile(r"maxmemory-policy\s+(\S+)")


def _policies() -> list[tuple[str, str]]:
    return [
        (str(path.relative_to(ROOT)), policy)
        for path in SOURCES
        for policy in _POLICY.findall(path.read_text())
    ]


def test_the_stack_sets_an_eviction_policy() -> None:
    """The scan reads the real files (a guard that finds nothing guards nothing)."""
    assert any("docker-compose" in path for path, _ in _policies())


@pytest.mark.parametrize("path, policy", _policies())
def test_no_policy_can_evict_the_queue(path: str, policy: str) -> None:
    assert not policy.startswith("allkeys-"), f"{path}: {policy}"
