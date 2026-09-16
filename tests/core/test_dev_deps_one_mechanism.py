"""Dev dependencies live in one place, and the default command installs them.

The template carried them in a ``dev`` extra AND a ``dev`` dependency group,
with every sync using ``--all-extras``. ``uv add --dev`` writes to the group
and re-syncs with uv's defaults - group yes, extras no - so adding one test
dependency uninstalled pytest (#1066).
"""

from __future__ import annotations

import tomllib

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _render(path: str, **overrides: object) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    # ``project_slug`` has no default: without it ``[project.scripts]``
    # renders an empty key and the result is not parseable TOML.
    context = {**get_copier_defaults(), "project_slug": "demo", **overrides}
    return env.get_template(f"{PROJECT_SLUG_PLACEHOLDER}/{path}").render(context)


def _pyproject(**overrides: object) -> dict:
    return tomllib.loads(_render("pyproject.toml.jinja", **overrides))


def test_the_test_runner_is_in_the_group_uv_installs_by_default() -> None:
    data = _pyproject()

    group = " ".join(data["dependency-groups"]["dev"])
    assert "pytest" in group
    assert "ruff" in group


def test_no_dev_extra_competes_with_the_group() -> None:
    """Two homes is what made ``uv add --dev`` destructive."""
    data = _pyproject()

    assert "dev" not in data.get("project", {}).get("optional-dependencies", {})


def test_the_commands_the_project_ships_do_not_rely_on_extras() -> None:
    """Makefile, Dockerfile and CI must install what the group holds."""
    for path in (
        "Makefile.jinja",
        "Dockerfile.jinja",
        ".github/workflows/ci.yml.jinja",
        "pyproject.toml.jinja",
    ):
        assert "--all-extras" not in _render(path), path
