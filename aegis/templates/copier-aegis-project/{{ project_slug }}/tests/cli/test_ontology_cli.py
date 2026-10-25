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


def _ask(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "app.cli.main", "ontology", *args]
    run = subprocess.run(command, capture_output=True, text=True)
    # What the command said on stderr, in the failure: CI keeps nothing else.
    assert not check or run.returncode == 0, run.stderr[-4000:]
    return run


def _found(*args: str) -> dict:
    return json.loads(_ask(*args).stdout)


class TestLookingUp:
    """What a coding agent asks before it plans (the plan-with-the-twin
    skill): the twin's answers from a shell, the same ones the MCP
    ``ontology`` tool gives, the app's routes in them."""

    def test_find_lists_the_parts_of_a_kind(self) -> None:
        nodes = _found("find", "--kind", "component")["nodes"]
        assert "component:backend" in {n["id"] for n in nodes}

    def test_a_node_says_what_it_is_wired_to(self) -> None:
        found = _found("node", "component:backend")
        assert found["node"]["id"] == "component:backend"
        assert "edges" in found and "neighbors" in found

    def test_several_nodes_in_one_ask(self) -> None:
        ids = [n["id"] for n in _found("find", "--kind", "component")["nodes"][:2]]
        assert [n["node"]["id"] for n in _found("node", *ids)["nodes"]] == ids

    def test_paths_run_between_two_parts(self) -> None:
        first, second = (
            n["id"] for n in _found("find", "--kind", "component")["nodes"][:2]
        )
        assert isinstance(_found("paths", first, second)["paths"], list)

    def test_a_route_walks_its_code_path(self) -> None:
        """Read with the app, as a shell has no running backend."""
        route = _found("find", "--kind", "route")["nodes"][0]["name"]
        assert "error" not in _found("route", route)

    def test_a_node_it_does_not_know_is_refused(self) -> None:
        run = _ask("node", "component:nope", check=False)
        assert run.returncode != 0
        assert "component:nope" in run.stderr + run.stdout
