"""``ontology export``: the app's system model in the formats other tools
read, printed alone, as a program reads it."""

import json
import subprocess
import sys

import yaml


def _export(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "app.cli.main", "ontology", "export", *args]
    return subprocess.run(command, capture_output=True, text=True, check=check)


def test_the_stack_page_lists_this_apps_parts() -> None:
    assert "`backend`" in _export().stdout


def test_the_stack_page_counts_the_apps_routes() -> None:
    """Built with the app, so its routes are in it, as a docs build has."""
    rows = [r.split("|") for r in _export().stdout.splitlines() if r.startswith("| `")]
    assert sum(int(row[4]) for row in rows) > 0


def test_the_catalog_has_the_stack_as_its_system() -> None:
    entities = list(yaml.safe_load_all(_export("--format", "backstage").stdout))
    assert entities[0]["kind"] == "System"
    assert any(e["kind"] == "Component" for e in entities)


def test_otel_names_the_process_asked_for() -> None:
    attributes = json.loads(_export("--format", "otel", "--unit", "worker").stdout)
    assert attributes["service.name"] == "worker"


def test_a_format_it_does_not_know_is_refused() -> None:
    run = _export("--format", "c4", check=False)
    assert run.returncode != 0
    assert "c4" in run.stderr + run.stdout
