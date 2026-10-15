"""``aegis add-service`` brings the template's queryspy baseline entries for
the files it writes.

A project's ``.queryspy-baseline.json`` is its own once ``make
check-queries-baseline`` rewrites it: entries for code it does not have yet
are gone. Adding a service then writes code whose known repeated queries the
template already baselines, and ``--queryspy-strict`` failed the service's
own tests until those entries were copied by hand.
"""

import json
import subprocess
from pathlib import Path

import pytest

from aegis.core.component_files import PROJECT_SLUG_PLACEHOLDER, get_template_path
from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command

BASELINE = ".queryspy-baseline.json"


def _entries(path: Path) -> list[dict[str, str]]:
    return json.loads(path.read_text())["entries"]


@pytest.mark.slow
def test_add_auth_merges_the_template_entries_for_its_files(
    project_factory: ProjectFactory,
) -> None:
    project_path = project_factory("base_with_database")
    baseline = project_path / BASELINE
    # The project's own baseline: nothing for auth, one entry of its own.
    own = {
        "kind": "n_plus_one",
        "label": "Mine",
        "file": "app/mine.py",
        "function": "f",
    }
    doc = json.loads(baseline.read_text())
    doc["entries"] = [own]
    baseline.write_text(json.dumps(doc, indent=2) + "\n")
    git = ["git", "-C", str(project_path)]
    subprocess.run([*git, "commit", "-qam", "own baseline"], check=True)
    template = _entries(get_template_path() / PROJECT_SLUG_PLACEHOLDER / BASELINE)
    before = {e["file"] for e in template if (project_path / e["file"]).exists()}

    result = run_aegis_command(
        "add-service", "auth", "--project-path", str(project_path), "--yes"
    )
    assert result.returncode == 0, f"add-service failed: {result.stderr}"

    # Exactly the template's entries for the files the add wrote.
    expected = [
        e
        for e in template
        if e["file"] not in before and (project_path / e["file"]).exists()
    ]
    assert any(e["file"].startswith("app/services/auth/") for e in expected)

    entries = _entries(baseline)
    assert sorted(map(str, entries)) == sorted(map(str, [own, *expected]))
    keys = [(e["kind"], e["label"], e["file"], e["function"]) for e in entries]
    assert len(keys) == len(set(keys)), "duplicate baseline entries"
    assert keys == sorted(keys, key=lambda k: tuple(p or "" for p in k))
