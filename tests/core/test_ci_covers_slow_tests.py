"""Every slow-marked test file runs somewhere in CI.

The PR run deselects ``-m slow``. Two tests sat red on main for weeks
because nothing ever ran them (the add/remove/update suites had no CI home
at all), and a real lifecycle regression would have looked identical. This
pins the property: a file carrying ``pytest.mark.slow`` is either driven
explicitly by the stack matrix or picked up by a workflow that runs
``-m slow`` and does not ``--ignore`` it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"


def _slow_test_files() -> set[str]:
    return {
        str(p.relative_to(REPO))
        for p in (REPO / "tests").rglob("test_*.py")
        if "pytest.mark.slow" in p.read_text()
    }


def _ci_homes() -> set[str]:
    """Files CI runs: named node ids, plus everything a ``-m slow`` run keeps."""
    covered: set[str] = set()
    slow_files = _slow_test_files()
    for wf in WORKFLOWS.glob("*.yml"):
        text = wf.read_text()
        covered |= {f for f in slow_files if f in text and "--ignore=" + f not in text}
        if re.search(r"pytest[^\n]*-m slow", text):
            ignored = set(re.findall(r"--ignore=(\S+)", text))
            covered |= slow_files - ignored
    return covered


def test_every_slow_test_file_has_a_ci_home() -> None:
    homeless = sorted(_slow_test_files() - _ci_homes())
    assert not homeless, "slow tests no workflow ever runs:\n  " + "\n  ".join(homeless)
