"""The generated conftest keeps every autouse fixture in every stack shape.

A ``{%- if %}`` that swallows the newline before it can glue the next
``@pytest.fixture(autouse=True)`` onto the end of a comment: the file still
parses, the fixture just stops being a fixture. The system-status cache
then leaked between tests and six stacks failed their health tests.
"""

from __future__ import annotations

import ast
import itertools
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

ALWAYS = {"_fresh_system_status_cache", "_clear_dependency_overrides"}


def _autouse(**overrides: Any) -> set[str]:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    rendered = env.get_template("{{ project_slug }}/tests/conftest.py.jinja").render(
        {**get_copier_defaults(), "project_slug": "demo", **overrides}
    )
    return {
        node.name
        for node in ast.parse(rendered).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any("autouse=True" in ast.unparse(d) for d in node.decorator_list)
    }


@pytest.mark.parametrize(
    ("finance", "auth", "database"),
    list(itertools.product([True, False], repeat=3)),
)
def test_every_stack_keeps_its_autouse_fixtures(
    finance: bool, auth: bool, database: bool
) -> None:
    fixtures = _autouse(
        include_finance=finance and database,
        include_auth=auth,
        include_database=database,
    )
    assert fixtures >= ALWAYS, f"lost: {sorted(ALWAYS - fixtures)}"
    assert ("_finance_calendar" in fixtures) is (finance and database)
