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


def test_the_image_installs_dependencies_in_a_layer_only_the_lock_reaches() -> None:
    """A README edit reinstalled every package: the dependency layer copied
    README.md, and the step deleted its uv cache. The lock alone reaches
    that layer, the cache is a build mount, and the project installs after
    the code is copied."""
    dockerfile = _render("Dockerfile.jinja")

    deps, project = dockerfile.split("COPY . /code", 1)
    assert "COPY pyproject.toml uv.lock /code/\n" in deps
    assert "uv sync --frozen --no-install-project" in deps
    assert "rm -rf /tmp/uv-cache" not in dockerfile
    # The mount is wherever UV_CACHE_DIR says, not a second copy of it.
    mount = "RUN --mount=type=cache,target=${UV_CACHE_DIR}"
    assert deps.count(mount) == 1
    assert f"{mount} \\\n    uv sync --frozen\n" in project
