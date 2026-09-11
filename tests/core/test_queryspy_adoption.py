"""The N+1 rule in CLAUDE.md is enforced by running the suite, not by review.

``queryspy`` is a pytest plugin built on SQLAlchemy 2.0's ``do_orm_execute``,
so it only means anything in a stack that has a database. It rides the dev
extra, never the runtime dependencies: a generated project ships the
capability, and its author decides what to do with it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _render(path: str, context: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())),
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(context)


def _ctx(**overrides: Any) -> dict[str, Any]:
    # ``project_slug`` has no copier default; without it ``[project.scripts]``
    # renders a nameless entry and the result is not parseable TOML.
    return {**get_copier_defaults(), "project_slug": "demo_app", **overrides}


class TestQuerySpyRidesTheDatabase:
    def test_dep_is_dev_only_and_gated_on_a_database(self) -> None:
        on = _render("pyproject.toml.jinja", _ctx(include_database=True))
        off = _render("pyproject.toml.jinja", _ctx(include_database=False))
        assert "queryspy" in on
        assert "queryspy" not in off

    def test_dep_is_not_a_runtime_dependency(self) -> None:
        """It must sit in the dev extra, never in ``[project] dependencies``."""
        import tomllib

        project = tomllib.loads(
            _render("pyproject.toml.jinja", _ctx(include_database=True))
        )["project"]
        runtime = " ".join(project["dependencies"])
        dev = " ".join(project["optional-dependencies"]["dev"])
        assert "queryspy" not in runtime
        assert "queryspy" in dev

    def test_check_queries_target_is_gated_the_same_way(self) -> None:
        on = _render("Makefile.jinja", _ctx(include_database=True))
        off = _render("Makefile.jinja", _ctx(include_database=False))
        assert "check-queries:" in on
        assert "check-queries:" not in off

    def test_poe_mirrors_the_make_target(self) -> None:
        """Windows has no ``make``; every target has a poe twin."""
        rendered = _render("pyproject.toml.jinja", _ctx(include_database=True))
        assert "[tool.poe.tasks.check-queries]" in rendered


class TestTheGateIsUp:
    BASELINE = Path("tests/fixtures/queryspy-baseline.json")

    def test_the_stack_matrix_runs_strict_against_the_baseline(self) -> None:
        """One suite run per stack carries the gate; no second pass."""
        source = Path("tests/cli/test_utils.py").read_text()
        assert "--queryspy-strict" in source
        assert "--queryspy-baseline=" in source

    def test_the_baseline_is_the_tools_own_format(self) -> None:
        import json

        doc = json.loads(self.BASELINE.read_text())
        assert doc["tool"] == "queryspy"
        assert {"kind", "label", "file", "function"} <= set(doc["entries"][0])

    def test_no_app_code_column_load_is_frozen_in(self) -> None:
        """``column_load`` in app code was one pattern - ``refresh()`` after a
        write, with no ``server_default`` anywhere - and it was fixed, not
        baselined. Test files re-reading a row a service updated are correct
        and stay. A new one in ``app/`` is a regression, not debt."""
        import json

        offenders = [
            f"{e['file']}:{e['function']}"
            for e in json.loads(self.BASELINE.read_text())["entries"]
            if e["kind"] == "column_load" and e["file"].startswith("app/")
        ]
        assert offenders == []

    def test_the_plugin_is_inert_unless_asked(self) -> None:
        """Installing it must not change a plain ``pytest`` run."""
        rendered = _render("pyproject.toml.jinja", _ctx(include_database=True))
        assert "queryspy_fail_on" not in rendered
        assert "queryspy_budget" not in rendered
