"""A failed ``add-service`` leaves the project as it found it.

Adding auth to a real project (2026-09-20) failed inside migration
generation after 53 files were written and the answers file already said
auth was enabled: the project had the service's code and none of its
schema, would not start, and a retry short-circuited on "already enabled".

The command now works like ``update``: it requires a clean tree, marks a
backup point, and on any failure resets to it. The tree is clean before
it starts, so the reset cannot take anything the user had not committed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from aegis.commands import add_service
from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command


def _git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=project, capture_output=True, text=True, check=True
    ).stdout


def _answers(project: Path) -> dict[str, object]:
    return yaml.safe_load((project / ".copier-answers.yml").read_text())


def _fail_migration_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("migrate_gen failed for auth: unable to open database file")

    monkeypatch.setattr(add_service, "generate_migration", boom)


@pytest.fixture
def project(project_factory: ProjectFactory) -> Path:
    path = project_factory("base_with_database")
    assert _git(path, "status", "--porcelain") == "", "fixture must start clean"
    return path


class TestAFailedAddIsUndone:
    def test_the_tree_is_exactly_as_it_was(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        head = _git(project, "rev-parse", "HEAD")
        _fail_migration_generation(monkeypatch)

        result = run_aegis_command(
            "add-service", "auth", "--project-path", str(project), "--yes"
        )

        assert result.returncode == 1
        assert _git(project, "status", "--porcelain") == "", (
            "files written before the failure are still in the tree"
        )
        assert _git(project, "rev-parse", "HEAD") == head

    def test_the_service_is_not_recorded_so_a_retry_is_possible(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = _answers(project)
        _fail_migration_generation(monkeypatch)

        run_aegis_command(
            "add-service", "auth", "--project-path", str(project), "--yes"
        )

        assert _answers(project) == before
        assert not _answers(project).get("include_auth")

    def test_no_backup_marker_is_left_behind(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fail_migration_generation(monkeypatch)

        run_aegis_command(
            "add-service", "auth", "--project-path", str(project), "--yes"
        )

        assert "aegis-backup" not in _git(project, "tag", "--list")


class TestADirtyTreeIsRefused:
    def test_nothing_is_written_when_the_tree_is_dirty(self, project: Path) -> None:
        """A reset on failure is only safe when there is nothing to lose."""
        (project / "notes.txt").write_text("uncommitted work\n")
        before = _answers(project)

        result = run_aegis_command(
            "add-service", "auth", "--project-path", str(project), "--yes"
        )

        assert result.returncode == 1
        assert _answers(project) == before
        assert _git(project, "status", "--porcelain").strip() == "?? notes.txt"
        assert (project / "notes.txt").read_text() == "uncommitted work\n"
