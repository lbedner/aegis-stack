"""An add formats what it wrote, never the rest of the project.

Post-gen ran the project's ``make fix`` (``ruff check --fix .`` and
``ruff format .``), so an ``add-service`` rewrote files it never touched:
on steward, five deliberately unformatted files in unrelated services.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from aegis.core.manual_updater import ManualUpdater

UGLY = "x = {  'a':1 }\n"


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'p'\n")
    (tmp_path / "theirs.py").write_text(UGLY)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "start")
    return tmp_path


def _updater(project: Path) -> ManualUpdater:
    updater = object.__new__(ManualUpdater)
    updater.project_path = project
    updater.answers = {}
    return updater


def test_only_the_files_the_add_changed_are_formatted(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "added.py").write_text(UGLY)
    (project / "notes.md").write_text("not python\n")
    ran: list[list[str]] = []
    real_run = subprocess.run

    def run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd[0] == "git":
            return real_run(cmd, **kwargs)
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    _updater(project).run_post_generation_tasks()

    formatting = [cmd for cmd in ran if "ruff" in cmd or "make" in cmd]
    assert formatting, ran
    for cmd in formatting:
        assert "make" not in cmd
        assert "." not in cmd and "theirs.py" not in cmd
        assert cmd[-1] == "added.py"


def test_without_changes_nothing_is_formatted(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: list[list[str]] = []
    real_run = subprocess.run

    def run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd[0] == "git":
            return real_run(cmd, **kwargs)
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    _updater(project).run_post_generation_tasks()

    assert not [cmd for cmd in ran if "ruff" in cmd or "make" in cmd]
