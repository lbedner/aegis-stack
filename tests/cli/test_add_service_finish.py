"""An add that leaves conflicts stops for them, and ``--finish`` completes it.

Adding ``auth[guest]`` to a customised project (2026-11-25) merged four
shared files with conflict markers, then generated migrations: that
imports the app, the import hit a marker, and the whole add rolled back.
An add with any conflict could never complete. Now it stops where
``update`` does: the markers stay for the user, nothing imports them, and
``aegis add-service --finish`` writes and applies the schema once they
are resolved.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from aegis.core.manual_updater import ManualUpdater, UpdateResult
from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command

SHARED = Path("app/core/config.py")  # imported by migration generation
MARKERS = "<<<<<<< your project\nmine = 1\n=======\ntheirs = 1\n>>>>>>> new template\n"


def _git(project: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=project, capture_output=True, text=True, check=True
    ).stdout


def _auth_enabled(project: Path) -> bool:
    answers = yaml.safe_load((project / ".copier-answers.yml").read_text())
    return answers.get("include_auth") is True


def _auth_revisions(project: Path) -> list[Path]:
    return list((project / "alembic" / "versions").glob("*_auth.py"))


def _leave_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    """The merge leaves markers in a shared module, as a real one does."""
    real = ManualUpdater.add_component

    def merged_with_markers(
        self: ManualUpdater, *args: Any, **kwargs: Any
    ) -> UpdateResult:
        result = real(self, *args, **kwargs)
        shared = self.project_path / SHARED
        if MARKERS not in shared.read_text():
            shared.write_text(shared.read_text() + MARKERS)
        return result

    monkeypatch.setattr(ManualUpdater, "add_component", merged_with_markers)


def _resolve(project: Path) -> None:
    shared = project / SHARED
    shared.write_text(shared.read_text().replace(MARKERS, ""))


@pytest.fixture
def conflicted(
    project_factory: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    project = project_factory("base_with_database")
    _leave_a_conflict(monkeypatch)
    result = run_aegis_command(
        "add-service", "auth", "--project-path", str(project), "--yes"
    )
    assert result.returncode == 0, result.stderr
    monkeypatch.undo()
    return project


@pytest.mark.slow
class TestAConflictedAdd:
    def test_keeps_what_it_wrote_and_the_markers(self, conflicted: Path) -> None:
        assert _auth_enabled(conflicted)
        assert MARKERS in (conflicted / SHARED).read_text()

    def test_writes_no_schema_while_the_markers_stand(self, conflicted: Path) -> None:
        assert _auth_revisions(conflicted) == []

    def test_keeps_its_backup_point(self, conflicted: Path) -> None:
        assert "aegis-backup" in _git(conflicted, "tag", "--list")


@pytest.mark.slow
class TestFinish:
    def test_is_refused_while_a_conflict_remains(self, conflicted: Path) -> None:
        result = run_aegis_command(
            "add-service", "--finish", "--project-path", str(conflicted)
        )
        assert result.returncode == 1
        assert str(SHARED) in result.stdout + result.stderr
        assert _auth_revisions(conflicted) == []

    def test_writes_the_schema_once_resolved(self, conflicted: Path) -> None:
        _resolve(conflicted)
        result = run_aegis_command(
            "add-service", "--finish", "--project-path", str(conflicted)
        )
        assert result.returncode == 0, result.stderr
        assert len(_auth_revisions(conflicted)) == 1
        assert "aegis-backup" not in _git(conflicted, "tag", "--list")

    def test_has_nothing_to_finish_twice(self, conflicted: Path) -> None:
        _resolve(conflicted)
        run_aegis_command("add-service", "--finish", "--project-path", str(conflicted))
        again = run_aegis_command(
            "add-service", "--finish", "--project-path", str(conflicted)
        )
        assert again.returncode == 1

    def test_a_failed_migration_keeps_it_finishable(
        self, conflicted: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _resolve(conflicted)
        monkeypatch.setattr(ManualUpdater, "write_schema", lambda *_: False)
        failed = run_aegis_command(
            "add-service", "--finish", "--project-path", str(conflicted)
        )
        assert failed.returncode == 1
        assert "aegis-backup" in _git(conflicted, "tag", "--list")

        monkeypatch.undo()
        again = run_aegis_command(
            "add-service", "--finish", "--project-path", str(conflicted)
        )
        assert again.returncode == 0, again.stderr
        assert len(_auth_revisions(conflicted)) == 1


@pytest.mark.slow
def test_a_plugin_dependency_that_stops_on_conflicts_is_finishable(
    project_factory: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``aegis add <plugin>`` installs its services through
    ``ManualUpdater.add_service``; its stop points at ``--finish`` too."""
    project = project_factory("base_with_database")
    _leave_a_conflict(monkeypatch)
    stopped = ManualUpdater(project).add_service("auth", run_post_gen=False)
    monkeypatch.undo()
    assert not stopped.success
    assert str(SHARED) in (stopped.error_message or "")

    _resolve(project)
    finished = run_aegis_command(
        "add-service", "--finish", "--project-path", str(project)
    )
    assert finished.returncode == 0, finished.stderr
    assert len(_auth_revisions(project)) == 1
