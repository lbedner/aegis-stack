"""The Dockerfile's plugin hooks: data files, not edits.

A plugin's only packaging levers used to be ``pyproject_deps`` and
``docker_services``. Anything a Python wheel cannot carry — ``ffmpeg``,
``poppler-utils``, a tarball — had no way into the image, and looping
plugins into ``Dockerfile.jinja`` would not work: the file is
``warn-if-diverged``, so a project that ever added a build step keeps its
Dockerfile and the plugin's packages never land.

So the Dockerfile carries two fixed hook blocks and plugins contribute
data: ``docker/apt-packages.txt`` (from every active plugin's
``docker_packages``) and ``docker/build.d/<plugin>.sh`` (their
``docker_steps``). These tests pin the data side and the blocks.
"""

from __future__ import annotations

from typing import Any

import pytest

from aegis.core.component_files import get_template_path
from aegis.core.plugins.spec import PluginKind, PluginSpec
from aegis.core.render_diff import build_template_env

APT_PACKAGES = "{{ project_slug }}/docker/apt-packages.txt.jinja"
DOCKERFILE = "{{ project_slug }}/Dockerfile.jinja"


def render(path: str, **context: Any) -> str:
    env = build_template_env(get_template_path())
    return env.get_template(path).render(project_slug="demo", **context)


def package_lines(rendered: str) -> list[str]:
    """The package lines: everything that is neither blank nor a comment."""
    return [
        line
        for line in rendered.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def plugin(name: str, **fields: Any) -> dict[str, Any]:
    """A serialized ``_plugins`` entry, as the composer writes it."""
    entry = {"name": name, "docker_packages": [], "docker_steps": []}
    entry.update(fields)
    return entry


class TestAptPackagesFile:
    def test_a_stack_without_plugins_installs_nothing(self) -> None:
        """The file always exists (the Dockerfile copies it) and is inert."""
        rendered = render(APT_PACKAGES, _plugins=[])

        assert package_lines(rendered) == []

    def test_a_plugin_package_is_listed_under_its_name(self) -> None:
        rendered = render(
            APT_PACKAGES, _plugins=[plugin("media", docker_packages=["ffmpeg"])]
        )

        assert package_lines(rendered) == ["ffmpeg"]
        assert "# media" in rendered

    def test_two_plugins_sharing_a_package_get_one_line(self) -> None:
        """apt rejects a repeated name in one install run only sometimes;
        one line is the contract either way."""
        rendered = render(
            APT_PACKAGES,
            _plugins=[
                plugin("media", docker_packages=["ffmpeg", "libpq-dev"]),
                plugin("video", docker_packages=["ffmpeg"]),
            ],
        )

        assert package_lines(rendered) == ["ffmpeg", "libpq-dev"]

    def test_a_plugin_without_packages_adds_no_section(self) -> None:
        rendered = render(
            APT_PACKAGES,
            _plugins=[plugin("blog"), plugin("media", docker_packages=["ffmpeg"])],
        )

        assert "# blog" not in rendered

    def test_removing_the_plugin_removes_its_lines(self) -> None:
        rendered = render(APT_PACKAGES, _plugins=[])

        assert "ffmpeg" not in rendered


class TestDockerfileHooks:
    def test_the_package_hook_reads_the_data_file(self) -> None:
        rendered = render(DOCKERFILE)

        assert "COPY docker/apt-packages.txt /tmp/apt-packages.txt" in rendered
        # xargs, not a shell: the names are never interpolated.
        assert "xargs -r apt-get install" in rendered

    def test_the_build_step_hook_runs_the_scripts_in_order(self) -> None:
        rendered = render(DOCKERFILE)

        assert "COPY docker/build.d/ /tmp/build.d/" in rendered
        assert "for step in $(ls /tmp/build.d/*.sh 2>/dev/null | sort)" in rendered

    def test_the_hooks_sit_above_the_application_copy(self) -> None:
        """A source change must not reinstall packages or rerun steps."""
        rendered = render(DOCKERFILE)

        assert rendered.index("docker/apt-packages.txt") < rendered.index(
            "COPY . /code"
        )
        assert rendered.index("docker/build.d/") < rendered.index("COPY . /code")

    def test_the_build_d_placeholder_ships(self) -> None:
        """The COPY needs the directory in the build context, always."""
        rendered = render("{{ project_slug }}/docker/build.d/README.md.jinja")

        assert "docker/build.d/" in rendered


class TestSpecValidation:
    """A bad name fails where the plugin author wrote it, not in the build."""

    def test_accepts_debian_package_names(self) -> None:
        spec = PluginSpec(
            name="media",
            kind=PluginKind.SERVICE,
            description="d",
            docker_packages=["ffmpeg", "libpq-dev", "g++"],
        )

        assert spec.docker_packages == ["ffmpeg", "libpq-dev", "g++"]

    @pytest.mark.parametrize(
        "package", ["FFmpeg", "ffmpeg; rm -rf /", "-y", "ffmpeg && curl evil"]
    )
    def test_refuses_anything_apt_would_not_take(self, package: str) -> None:
        with pytest.raises(ValueError, match="docker_packages"):
            PluginSpec(
                name="media",
                kind=PluginKind.SERVICE,
                description="d",
                docker_packages=[package],
            )

    @pytest.mark.parametrize("step", ["../escape", "a b", "step.sh/../../x"])
    def test_refuses_a_step_that_is_not_a_script_name(self, step: str) -> None:
        with pytest.raises(ValueError, match="docker_steps"):
            PluginSpec(
                name="media",
                kind=PluginKind.SERVICE,
                description="d",
                docker_steps=[step],
            )
