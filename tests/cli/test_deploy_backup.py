"""What ``aegis deploy-backup`` / the pre-deploy backup capture, and what a
rollback puts back (aegis-stack#1560).

The deploy directory copy (``files/``) took SQLite as a live file, which
under WAL is not a consistent copy, and never saw the object store, a
named volume outside the directory. Every remote command is recorded
instead of run, so these pin the shell each step sends.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aegis.commands import deploy as deploy_mod
from aegis.commands.deploy import _create_backup, _rollback_to_backup
from aegis.commands.deploy_backup import (
    DATABASE_FILE,
    RESTORE,
    SNAPSHOT,
    is_sqlite,
    offsite_env,
    snapshot_sqlite,
)
from aegis.core.deploy_protocol import protocol

TS = "2026-01-01_000000"


def _recorder(calls: list[str], fail: tuple[str, ...] = ()):
    def _fake(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        calls.append(command)
        code = 1 if any(marker in command for marker in fail) else 0
        return subprocess.CompletedProcess([], returncode=code, stdout="", stderr="")

    return _fake


def _backup(
    monkeypatch: pytest.MonkeyPatch, *, sqlite: bool, fail: tuple[str, ...] = ()
) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(deploy_mod, "_run_remote_capture", _recorder(calls, fail))
    assert _create_backup("h", "u", "/srv/app", include_db=True, sqlite=sqlite)
    return calls


def _rsync(calls: list[str]) -> str:
    return next(c for c in calls if "rsync" in c)


def _bash_parses(command: str) -> None:
    result = subprocess.run(["bash", "-n", "-c", command], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


class TestSqliteSnapshot:
    def test_backup_snapshots_into_its_own_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _backup(monkeypatch, sqlite=True)

        snapshot = next(c for c in calls if "python -c" in c)
        assert f"exec -T webserver python -c {shlex.quote(SNAPSHOT)}" in snapshot
        assert re.search(r"> /srv/app/backups/[0-9_-]+/database\.db ", snapshot)
        _bash_parses(snapshot)

    def test_the_snapshot_makes_the_backup_directory_it_writes_into(
        self, tmp_path: Path
    ) -> None:
        """It runs before anything else of the backup exists. Run for real,
        with ``echo`` standing in for docker compose."""

        def bash(command: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", "-c", command], capture_output=True, text=True
            )

        backup = tmp_path / "backups" / TS
        assert snapshot_sqlite(bash, "echo", str(backup))
        assert (backup / DATABASE_FILE).read_text().startswith("exec -T webserver")

    def test_file_copy_skips_the_live_database_once_snapshotted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rollback would otherwise lay the live copy's stale -wal back
        down beside the consistent snapshot."""
        calls = _backup(monkeypatch, sqlite=True)

        assert "--exclude /data" in _rsync(calls)
        assert calls.index(next(c for c in calls if "python -c" in c)) < calls.index(
            _rsync(calls)
        )

    def test_failed_snapshot_falls_back_to_the_file_copy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _backup(monkeypatch, sqlite=True, fail=("python -c",))

        assert "--exclude /data" not in _rsync(calls)

    def test_postgres_projects_take_no_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _backup(monkeypatch, sqlite=False)

        assert not any("python -c" in c for c in calls)
        assert "--exclude /data" not in _rsync(calls)


def test_backup_archives_the_object_store(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _backup(monkeypatch, sqlite=False)

    archive = next(c for c in calls if "storage.tar.gz" in c)
    assert "exec -T webserver tar -czf - -C /data/storage ." in archive
    _bash_parses(archive)


class TestSteps:
    """Marked for the deploy agent's step bar (``progress_line``), in the
    order they run; ``offsite`` only when the server pushes one."""

    def _marked(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        monkeypatch.setenv(protocol.PROTOCOL["progress_env"], "1")
        _backup(monkeypatch, **kwargs)
        lines = capsys.readouterr().out.splitlines()
        return [p for line in lines if (p := protocol.read_progress(line))]

    def test_sqlite_marks_the_database_first(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = ["database", "files", "documents", "offsite"]
        assert self._marked(monkeypatch, capsys, sqlite=True) == [
            {"steps": plan, "at": key} for key in plan
        ]

    def test_without_offsite_there_is_no_offsite_step(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marked = self._marked(
            monkeypatch, capsys, sqlite=False, fail=("test -f /etc/aegis/",)
        )
        assert [m["at"] for m in marked] == ["files", "database", "documents"]
        assert all(m["steps"] == ["files", "database", "documents"] for m in marked)

    def test_in_a_terminal_nothing_is_marked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv(protocol.PROTOCOL["progress_env"], raising=False)
        _backup(monkeypatch, sqlite=True)
        assert "::aegis-progress" not in capsys.readouterr().out


class TestOffsite:
    def test_unconfigured_server_pushes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _backup(monkeypatch, sqlite=True, fail=("test -f /etc/aegis/",))

        assert not any("restic backup" in c for c in calls)

    def test_configured_server_pushes_everything_but_the_files(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``files/`` holds the server's ``.env``: it never leaves the box."""
        calls = _backup(monkeypatch, sqlite=True)

        push = next(c for c in calls if "restic backup" in c)
        assert offsite_env("/srv/app") in push
        assert "--exclude /srv/app/backups/" in push and "/files" in push
        _bash_parses(push)

    def test_env_file_lives_outside_the_deploy_directory(self) -> None:
        """A deploy rsyncs with --delete: inside the directory it is wiped."""
        assert not offsite_env("/srv/app").startswith("/srv/app/")


class TestRollback:
    def _rollback(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []
        monkeypatch.setattr(deploy_mod, "_run_remote_capture", _recorder(calls))
        monkeypatch.setattr(deploy_mod, "_run_remote", _recorder(calls))
        assert _rollback_to_backup("h", "u", "/srv/app", TS)
        return calls

    def test_restores_the_snapshot_and_the_object_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._rollback(monkeypatch)

        restore = next(c for c in calls if "storage.tar.gz" in c)
        assert (
            "run --rm --no-deps -T --entrypoint python webserver"
            f" -c {shlex.quote(RESTORE)} < /srv/app/backups/{TS}/database.db"
        ) in restore
        # A backup from before #1627 holds a data/ directory instead.
        assert f"cp -a /srv/app/backups/{TS}/data/. /srv/app/data/" in restore
        assert "run --rm --no-deps -T --entrypoint sh webserver" in restore
        _bash_parses(restore)
        # After the files land (their --delete clears data/), before start.
        assert calls.index(_rsync(calls)) < calls.index(restore)
        assert calls.index(restore) < calls.index(
            next(c for c in calls if "up -d --build" in c)
        )

    def test_backup_without_files_restores_data_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An off-box copy comes back without ``files/``: an rsync --delete
        from a missing directory must not be attempted."""
        calls = self._rollback(monkeypatch)

        assert f"[ ! -d /srv/app/backups/{TS}/files ] ||" in _rsync(calls)


@pytest.mark.parametrize(
    "answers,expected",
    [
        ({"include_database": True, "database_engine": "sqlite"}, True),
        ({"include_database": True, "database_engine": "postgres"}, False),
        ({"include_database": False, "database_engine": "sqlite"}, False),
        ({}, False),
    ],
)
def test_is_sqlite(answers: dict[str, object], expected: bool) -> None:
    assert is_sqlite(answers) is expected
