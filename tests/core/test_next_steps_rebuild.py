"""Next steps after a command that changes what a project installs: what
it added is not importable until the image is rebuilt, so the steps say to
rebuild first (#1523: the app crashed on a missing ``fastmcp`` after
``aegis add mcp``). Whether to is read from the outcome, the project's
dependencies before and after (``project_deps``), not from each spec."""

from pathlib import Path

import pytest

from aegis.constants import Messages
from aegis.core import project_deps


def test_the_steps_say_to_rebuild_when_it_brings_dependencies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Messages.print_next_steps(rebuild=True)

    out = capsys.readouterr().out
    assert "make rebuild" in out
    assert out.index("make rebuild") < out.index("make check")


def test_nothing_to_rebuild_says_nothing_about_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Messages.print_next_steps()

    assert "make rebuild" not in capsys.readouterr().out


def _project(path: Path, deps: list[str]) -> Path:
    listed = ", ".join(f'"{d}"' for d in deps)
    (path / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\ndependencies = [{listed}]\n'
        '[dependency-groups]\ndev = ["pytest"]\n'
    )
    return path


def test_the_dependencies_are_what_the_image_installs(tmp_path: Path) -> None:
    """``[project].dependencies``; a dev group never reaches the image."""
    project = _project(tmp_path, ["fastapi>=0.1", "cryptography>=42"])

    assert project_deps.dependencies(project) == frozenset(
        {"fastapi>=0.1", "cryptography>=42"}
    )


def test_a_project_without_a_readable_pyproject_has_none(tmp_path: Path) -> None:
    assert project_deps.dependencies(tmp_path) == frozenset()
    (tmp_path / "pyproject.toml").write_text("not = [toml")
    assert project_deps.dependencies(tmp_path) == frozenset()


def test_a_conflicted_update_remembers_what_it_started_with(tmp_path: Path) -> None:
    """``aegis update --finish`` compares against the dependencies from
    before the update, not from before the finish."""
    import subprocess

    from aegis.commands import update

    # The record lives in the project's git directory.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    update._record_pending_update(
        tmp_path,
        target_ref="v1",
        template_root=tmp_path,
        backup_tag=None,
        target_commit="abc",
        installed=frozenset({"fastapi>=0.1"}),
    )

    pending = update._load_pending_update(tmp_path)

    assert pending is not None
    assert update._installed_before(pending) == frozenset({"fastapi>=0.1"})
