"""No migration from the host while the project's containers hold its SQLite file.

The dev stack bind-mounts ``data/app.db``. Migrating it from the host left
the webserver's and scheduler's open connections reading a torn view
through Docker Desktop's file sharing ("database disk image is malformed")
until they restarted. The file was fine; every page errored anyway.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from aegis.core import post_gen_tasks
from aegis.core.copier_manager import load_copier_answers
from tests.cli.conftest import ProjectFactory
from tests.cli.test_utils import run_aegis_command


def _docker_reports(
    monkeypatch: pytest.MonkeyPatch, stdout: str | Exception
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: Any) -> Any:
        calls.append(cmd)
        if isinstance(stdout, Exception):
            raise stdout
        return subprocess.CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(post_gen_tasks.subprocess, "run", run)
    return calls


@pytest.fixture
def sqlite_project(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "data/app.db").write_bytes(b"")
    (tmp_path / "alembic").mkdir()
    (tmp_path / "alembic/alembic.ini").write_text("[alembic]\n")
    return tmp_path


class TestStackHoldsSqlite:
    def test_running_containers_hold_it(
        self, sqlite_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _docker_reports(monkeypatch, "3f2a1b\n")
        assert post_gen_tasks.stack_holds_sqlite(sqlite_project)

    def test_a_stopped_stack_does_not(
        self, sqlite_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _docker_reports(monkeypatch, "")
        assert not post_gen_tasks.stack_holds_sqlite(sqlite_project)

    def test_no_docker_means_nothing_holds_it(
        self, sqlite_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _docker_reports(monkeypatch, FileNotFoundError("docker"))
        assert not post_gen_tasks.stack_holds_sqlite(sqlite_project)

    def test_without_a_sqlite_file_docker_is_not_asked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _docker_reports(monkeypatch, "3f2a1b\n")
        assert not post_gen_tasks.stack_holds_sqlite(tmp_path)
        assert calls == []


def test_migrations_refuse_while_the_stack_holds_it(
    sqlite_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _docker_reports(monkeypatch, "3f2a1b\n")

    assert not post_gen_tasks.run_migrations(sqlite_project, include_migrations=True)
    assert all(cmd[0] == "docker" for cmd in calls), calls


def test_add_service_refuses_before_writing_anything(
    project_factory: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = project_factory("base_with_database")
    monkeypatch.setattr(
        "aegis.commands.add_service.stack_holds_sqlite", lambda _path: True
    )

    result = run_aegis_command(
        "add-service", "auth", "--project-path", str(project), "--yes"
    )

    assert result.returncode == 1
    assert "make stop" in result.stdout + result.stderr
    assert not load_copier_answers(project).get("include_auth")
    assert not (project / "app/services/auth").exists()
