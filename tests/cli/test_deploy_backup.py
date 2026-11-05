"""What ``aegis deploy-backup`` / the pre-deploy backup capture, and what a
rollback puts back (aegis-stack#1560).

The deploy directory copy (``files/``) took SQLite as a live file, which
under WAL is not a consistent copy, and never saw the object store, a
named volume outside the directory. Every remote command is recorded
instead of run, so these pin the shell each step sends.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest
import typer
import yaml
from typer.testing import CliRunner

from aegis.__main__ import app
from aegis.commands import deploy as deploy_mod
from aegis.commands.deploy import _create_backup, _rollback_to_backup
from aegis.commands.deploy_backup import (
    DATABASE_FILE,
    RESTORE,
    SNAPSHOT,
    is_sqlite,
    list_backups,
    snapshot_sqlite,
)
from aegis.core.deploy_protocol import protocol
from aegis.i18n import t

TS = "2026-01-01_000000"
SERVER = {"host": "h", "user": "u", "path": "/srv/app"}


def _answering(
    monkeypatch: pytest.MonkeyPatch, *fail: str, code: int = 1, err: str = ""
) -> list[str]:
    """A server every call succeeds on but those naming a ``fail`` marker."""
    calls: list[str] = []

    def remote(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        calls.append(command)
        answer = (code, err) if any(m in command for m in fail) else (0, "")
        return subprocess.CompletedProcess([], answer[0], "", answer[1])

    monkeypatch.setattr(deploy_mod, "_run_remote_capture", remote)
    monkeypatch.setattr(deploy_mod, "_run_remote", remote)
    return calls


def _backup(
    monkeypatch: pytest.MonkeyPatch, *, sqlite: bool, fail: tuple[str, ...] = ()
) -> list[str]:
    calls = _answering(monkeypatch, *fail)
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
    order they run."""

    def _marked(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        monkeypatch.setenv(protocol.PROTOCOL["progress_env"], "backup")
        _backup(monkeypatch, **kwargs)
        lines = capsys.readouterr().out.splitlines()
        return [p for line in lines if (p := protocol.read_progress(line))]

    def test_sqlite_marks_the_database_first(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = ["database", "files", "documents"]
        assert self._marked(monkeypatch, capsys, sqlite=True) == [
            {"steps": plan, "at": key} for key in plan
        ]

    def test_postgres_dumps_the_database_after_the_files(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        marked = self._marked(monkeypatch, capsys, sqlite=False)
        assert [m["at"] for m in marked] == ["files", "database", "documents"]
        assert all(m["steps"] == ["files", "database", "documents"] for m in marked)

    @pytest.mark.parametrize("outer", ["deploy", "provision"])
    def test_inside_another_command_the_backup_marks_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        outer: str,
    ) -> None:
        """The bar is the action the agent ran (its ``progress_env``): a
        deploy's backup, a provision's deploy, would replace its steps with
        ones it does not have."""
        monkeypatch.setenv(protocol.PROTOCOL["progress_env"], outer)
        _answering(monkeypatch)
        assert _create_backup("h", "u", "/srv/app", sqlite=True)
        assert "::aegis-progress" not in capsys.readouterr().out

    def test_in_a_terminal_nothing_is_marked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv(protocol.PROTOCOL["progress_env"], raising=False)
        _backup(monkeypatch, sqlite=True)
        assert "::aegis-progress" not in capsys.readouterr().out


def test_the_servers_backups_are_listed_in_one_call(tmp_path: Path) -> None:
    """Newest first, each with its size and whether it holds the database
    (a SQLite snapshot, a Postgres dump, or a pre-#1627 ``data/``); a
    stray directory is no backup. Run for real, in one remote call (the
    listing used to make two per backup)."""
    root = tmp_path / "backups"
    for name, held in (
        ("2026-10-13_020000", "data"),
        ("2026-10-14_020000", None),
        ("2026-10-15_020000", DATABASE_FILE),
    ):
        (root / name / "files").mkdir(parents=True)
        if held == "data":
            (root / name / "data").mkdir()
        elif held:
            (root / name / held).write_text("x" * 2048)
        os.utime(root / name, (int(name[8:10]), int(name[8:10])))
    (root / "lost+found").mkdir()
    calls: list[str] = []

    def bash(command: str) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.run(["bash", "-c", command], capture_output=True, text=True)

    listed = list_backups(bash, str(tmp_path))
    assert [(b["name"], b["database"]) for b in listed] == [
        ("2026-10-15_020000", True),
        ("2026-10-14_020000", False),
        ("2026-10-13_020000", True),
    ]
    assert all(b["size"] for b in listed)
    assert len(calls) == 1
    assert list_backups(bash, str(tmp_path / "nothing-yet")) == []


def test_a_failed_listing_is_refused_not_an_empty_list() -> None:
    """A dropped connection is not a server with no backups: the Overseer
    keeps what this returns for an hour."""

    def down(command: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], 255, "", "ssh: timed out")

    with pytest.raises(protocol.RefusedError, match="ssh: timed out"):
        list_backups(down, "/srv/app")


@pytest.mark.parametrize(
    ("code", "err", "warned"),
    [
        (1, "no such service: postgres", False),
        (1, "Cannot connect to the Docker daemon", True),
        (255, "ssh: timed out", True),
        (0, "", True),
    ],
)
def test_a_postgres_backup_without_its_dump_says_so(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    code: int,
    err: str,
    warned: bool,
) -> None:
    """Only compose saying the stack has no postgres is no dump to take: a
    failed call, or a postgres not running, would otherwise be a backup
    holding no database, said by nothing."""
    _answering(monkeypatch, "ps postgres", code=code, err=err)
    assert _create_backup("h", "u", "/srv/app", include_db=True, sqlite=False)
    assert (t("deploy.backup_db_failed") in capsys.readouterr().out) is warned


def test_a_sqlite_backup_looks_for_no_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not any("ps postgres" in c for c in _backup(monkeypatch, sqlite=True))


def test_a_deploy_stops_when_its_backup_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Going on would leave nothing to roll back to; ``--no-backup`` is how
    to mean that."""
    monkeypatch.setattr(deploy_mod, "_create_backup", lambda *a, **k: None)
    with pytest.raises(typer.Exit):
        deploy_mod._backed_up("h", "u", "/srv/app")


def test_a_deployment_it_cannot_check_is_not_a_first_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped connection read as nothing deployed skips the backup."""
    (tmp_path / ".aegis").mkdir()
    (tmp_path / ".aegis" / "deploy.yml").write_text(yaml.safe_dump({"server": SERVER}))
    (tmp_path / ".env").write_text(
        f"APP_ENV=prod\nAUTH_ENABLED=true\nSECRET_KEY={'0123456789abcdef' * 4}\n"
    )
    monkeypatch.setattr(deploy_mod, "_check_disk_space", lambda *a: None)
    calls = _answering(monkeypatch, "test -f", code=255, err="ssh: timed out")
    result = CliRunner().invoke(app, ["deploy", "--project-path", str(tmp_path)])
    assert result.exit_code == 1
    assert "ssh: timed out" in result.output
    assert not any("rsync" in c or " down " in c for c in calls)


def test_an_unreadable_backups_folder_is_refused_not_empty(tmp_path: Path) -> None:
    def run(command: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", command], capture_output=True, text=True, cwd=tmp_path
        )

    assert list_backups(run, str(tmp_path)) == []
    folder = tmp_path / "backups"
    folder.mkdir(mode=0)
    if os.access(folder, os.X_OK):
        pytest.skip("running as root")
    try:
        with pytest.raises(protocol.RefusedError):
            list_backups(run, str(tmp_path))
    finally:
        folder.chmod(0o700)


@pytest.mark.parametrize("marker", ["test -d", "test -f"])
def test_a_rollback_it_cannot_check_stops_before_touching_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, marker: str
) -> None:
    """A dropped connection is neither "no such backup" nor "no dump": the
    second would restore the files and silently leave the database."""
    calls = _answering(monkeypatch, marker, code=255, err="ssh: timed out")
    assert not _rollback_to_backup("h", "u", "/srv/app", TS)
    assert "ssh: timed out" in capsys.readouterr().err
    assert not any(" down " in c or "rsync" in c for c in calls)


def test_a_failed_lookup_of_the_latest_is_not_no_backups(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _answering(monkeypatch, "ls -1t", code=255, err="ssh: timed out")
    monkeypatch.setattr(
        deploy_mod, "_require_deploy_config", lambda _: {"server": SERVER}
    )
    with pytest.raises(typer.Exit):
        deploy_mod.deploy_rollback_command(backup=None, project_path=None)
    said = capsys.readouterr().err
    assert "ssh: timed out" in said
    assert t("deploy.no_backups_available") not in said


def test_a_backup_without_a_dump_still_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _answering(monkeypatch, "test -f")
    assert _rollback_to_backup("h", "u", "/srv/app", TS)
    assert not any("psql" in c for c in calls)


def test_a_refusal_inside_a_recorded_command_is_said_and_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    told: list[dict[str, Any]] = []
    monkeypatch.setattr(
        deploy_mod, "_tell_app", lambda *a: told.append(json.loads(a[-1]))
    )
    with (
        pytest.raises(typer.Exit) as stopped,
        deploy_mod.recorded(tmp_path, SERVER, "upload-storage"),
    ):
        raise protocol.RefusedError("no answer")
    assert stopped.value.exit_code == 1
    assert "no answer" in capsys.readouterr().err
    assert told[0]["summary"] == "no answer"
    assert told[0]["outcome"] == protocol.EVENT_FAILED


class TestStaysOnTheServer:
    def test_a_backup_is_never_pushed_off_the_server(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The copy that leaves is the app's nightly one (its off-site job),
        never this: ``files/`` holds the server's ``.env``."""
        calls = _backup(monkeypatch, sqlite=True)

        assert not any("restic" in c for c in calls)


class TestRollback:
    def _rollback(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls = _answering(monkeypatch)
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
