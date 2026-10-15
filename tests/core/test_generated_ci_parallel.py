"""A generated project's tests run in parallel, locally and in CI (#1647).

The template ran the whole suite in one process. Now pytest-xdist runs a
worker per CPU, and CI splits the suite into two jobs with ``--shard``
(tests/_shard.py in the project), behind one required ``test`` check.
"""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from typing import Any

import yaml

from aegis.core.component_files import get_template_path
from tests.core.test_dev_deps_one_mechanism import (
    PROJECT_SLUG_PLACEHOLDER,
    _pyproject,
    _render,
)


def _ci(**overrides: object) -> dict:
    return yaml.safe_load(_render(".github/workflows/ci.yml.jinja", **overrides))


def test_a_worker_per_cpu_even_with_psutil_installed() -> None:
    """xdist's ``auto`` counts physical cores once psutil is importable,
    and the template ships psutil: half a GitHub runner."""
    data = _pyproject()

    assert any(
        dep.startswith("pytest-xdist") for dep in data["dependency-groups"]["dev"]
    )
    assert "-n logical" in data["tool"]["pytest"]["ini_options"]["addopts"]


def test_ci_runs_two_shards_behind_one_required_check() -> None:
    for database in (True, False):
        jobs = _ci(include_database=database)["jobs"]

        assert jobs["test-shard"]["strategy"]["matrix"]["shard"] == [1, 2]
        run = jobs["test-shard"]["steps"][-1]["run"]
        assert "--shard ${{ matrix.shard }}/2" in run
        assert jobs["test"]["needs"] == ["test-shard"]
        assert jobs["test"]["if"] == "always()"


def test_the_baseline_rewrite_runs_in_one_process() -> None:
    """Under xdist the controller writes the baseline and runs no tests,
    so the file would come out empty."""
    makefile = _render("Makefile.jinja", include_database=True)
    pyproject = _render("pyproject.toml.jinja", include_database=True)
    for source in (makefile, pyproject):
        line = next(
            ln for ln in source.splitlines() if "--queryspy-baseline-update" in ln
        )
        assert "pytest -n 0 " in line


def _shard_module() -> Any:
    path = get_template_path() / PROJECT_SLUG_PLACEHOLDER / "tests" / "_shard.py"
    spec = importlib.util.spec_from_file_location("generated_shard", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _item(nodeid: str, group: str | None = None) -> SimpleNamespace:
    marker = SimpleNamespace(args=(group,)) if group else None
    return SimpleNamespace(nodeid=nodeid, get_closest_marker=lambda name: marker)


def test_the_shards_split_every_test_once_and_evenly() -> None:
    """Every job collects the same tests and agrees on the split: each test
    runs in exactly one shard, a file or an ``xdist_group`` stays whole, and
    the shards come out even in size."""
    shard = _shard_module()
    sizes = {"a": 40, "b": 25, "c": 20, "d": 10, "e": 5}
    tests = [
        _item(f"tests/test_{name}.py::t{i}")
        for name, count in sizes.items()
        for i in range(count)
    ]
    tests += [_item(f"tests/test_{f}.py::serial", group="db") for f in "xy"]
    ran: list[list[str]] = []
    for k in (1, 2):
        items = list(tests)
        dropped: list[Any] = []
        config = SimpleNamespace(
            getoption=lambda name, k=k: f"{k}/2",
            hook=SimpleNamespace(
                pytest_deselected=lambda items, dropped=dropped: dropped.extend(items)
            ),
        )
        shard.pytest_collection_modifyitems(config, items)
        assert len(items) + len(dropped) == len(tests)
        ran.append([item.nodeid for item in items])

    assert sorted(ran[0] + ran[1]) == sorted(t.nodeid for t in tests)
    files = [{nodeid.split("::")[0] for nodeid in run} for run in ran]
    assert not files[0] & files[1]
    serial = [{n for n in run if n.endswith("::serial")} for run in ran]
    assert sorted(map(len, serial)) == [0, 2]
    assert abs(len(ran[0]) - len(ran[1])) <= 2
