"""``aegis deploy-upload-db``: this machine's SQLite database onto the
server (aegis-stack#1619). Both in-container scripts (``deploy_backup``'s,
shared with backups and rollbacks) run for real against a stand-in
``app.core.db``; the SSH and docker calls are recorded."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import typer

from aegis.commands import deploy_upload
from aegis.commands.deploy_backup import RESTORE, SNAPSHOT, STORAGE_ROOT
from aegis.commands.deploy_upload import upload_db, upload_storage

SERVER = {"host": "h", "user": "u", "path": "/opt/app"}


def _app(root: Path, path: str = "./data/app.db") -> None:
    """A project whose ``app.core.db`` prints on import, as an app may."""
    (root / "app" / "core").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "core" / "__init__.py").write_text("")
    (root / "app" / "core" / "db.py").write_text(
        f"print('noise on import')\nDATABASE_PATH = {path!r}\n"
    )
    (root / "data").mkdir()


def _script(root: Path, script: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        input=stdin,
        capture_output=True,
    )


def _db(path: Path, value: str) -> None:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE t (v TEXT)")
    db.execute("INSERT INTO t VALUES (?)", (value,))
    db.commit()
    db.close()


def _value(path: Path) -> str:
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT v FROM t").fetchone()[0]
    finally:
        db.close()


def test_the_snapshot_reads_through_the_wal_and_writes_only_the_database(
    tmp_path: Path,
) -> None:
    """A byte copy of a live WAL database misses what is not checkpointed."""
    _app(tmp_path)
    live = sqlite3.connect(tmp_path / "data" / "app.db")
    live.execute("PRAGMA journal_mode=wal")
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("CREATE TABLE t (v TEXT)")
    live.execute("INSERT INTO t VALUES ('newest')")
    live.commit()
    try:
        done = _script(tmp_path, SNAPSHOT)
    finally:
        live.close()
    assert done.returncode == 0, done.stderr
    (tmp_path / "copy.db").write_bytes(done.stdout)
    assert _value(tmp_path / "copy.db") == "newest"


def test_the_snapshot_finds_a_database_kept_in_a_volume(tmp_path: Path) -> None:
    """``DATABASE_PATH`` outside ``./data`` (a named volume at ``/data/db``,
    the app in ``/code``): the backups' old script named the copy relative
    to ``./data`` and failed there, so no backup held the database
    (aegis-stack#1627)."""
    volume = tmp_path / "volume" / "db"
    volume.mkdir(parents=True)
    _app(tmp_path, str(volume / "app.db"))
    _db(volume / "app.db", "kept")
    done = _script(tmp_path, SNAPSHOT)
    assert done.returncode == 0, done.stderr
    (tmp_path / "copy.db").write_bytes(done.stdout)
    assert _value(tmp_path / "copy.db") == "kept"


def test_the_restore_puts_the_upload_in_place_of_the_database(tmp_path: Path) -> None:
    _app(tmp_path)
    live = tmp_path / "data" / "app.db"
    _db(live, "server's")
    (tmp_path / "data" / "app.db-wal").write_bytes(b"stale")
    _db(tmp_path / "upload.db", "mine")
    done = _script(tmp_path, RESTORE, (tmp_path / "upload.db").read_bytes())
    assert done.returncode == 0, done.stderr
    assert _value(live) == "mine"
    assert not (tmp_path / "data" / "app.db-wal").exists()
    assert not (tmp_path / "data" / "app.db.upload").exists()


@pytest.mark.parametrize(
    "upload", [b"", b"not a database, just bytes" * 200], ids=["empty", "junk"]
)
def test_the_restore_refuses_anything_but_a_whole_database(
    tmp_path: Path, upload: bytes
) -> None:
    """An empty upload is a valid empty database to SQLite: never put in."""
    _app(tmp_path)
    live = tmp_path / "data" / "app.db"
    _db(live, "server's")
    done = _script(tmp_path, RESTORE, upload)
    assert done.returncode != 0
    assert _value(live) == "server's"
    assert not (tmp_path / "data" / "app.db.upload").exists()


class _Server:
    """Records what reaches the server, in order."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.uploaded = b""

    def remote(
        self, host: str, user: str, command: str, upload: Path | None = None
    ) -> subprocess.CompletedProcess:
        self.calls.append(command)
        if upload is not None:
            self.uploaded = upload.read_bytes()
        return subprocess.CompletedProcess([], 0, "", "")


def _upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot: bytes | None
) -> _Server:
    server = _Server()

    def snap(root: Path, out: Path) -> bool:
        if snapshot is None:
            return False
        out.write_bytes(snapshot)
        return True

    monkeypatch.setattr(deploy_upload, "_snapshot", snap)
    monkeypatch.setattr(deploy_upload, "_run_remote_capture", server.remote)

    def backup(*args: object, **kwargs: object) -> str:
        server.calls.append("backup")
        return "2026-01-01_000000"

    monkeypatch.setattr(deploy_upload, "_create_backup", backup)
    return server


def test_the_upload_backs_up_stops_restores_and_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = _upload(monkeypatch, tmp_path, b"SQLite format 3\x00 mine")
    upload_db(tmp_path, SERVER)
    backup, down, restore, up, check = server.calls
    assert backup == "backup"
    assert down.endswith("down")
    assert "run --rm --no-deps -T --entrypoint python webserver -c" in restore
    assert up.endswith("up -d")
    assert check.endswith("storage check")
    assert server.uploaded == b"SQLite format 3\x00 mine"


def test_without_a_local_snapshot_the_server_is_never_touched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server = _upload(monkeypatch, tmp_path, None)
    with pytest.raises(typer.Exit):
        upload_db(tmp_path, SERVER)
    assert server.calls == []


GONE = [f"sha256/{d[:2]}/{d[2:4]}/{d}" for d in ("a" * 64, "b" * 64)]


class _Store(_Server):
    """A server whose ``storage check`` answers in turn from ``checks``
    (exit code, stdout)."""

    def __init__(self, *checks: tuple[int, str]) -> None:
        super().__init__()
        self.checks = list(checks)

    def remote(
        self, host: str, user: str, command: str, upload: Path | None = None
    ) -> subprocess.CompletedProcess:
        super().remote(host, user, command, upload)
        if command.endswith("storage check"):
            code, out = self.checks.pop(0)
            return subprocess.CompletedProcess([], code, out, "")
        return subprocess.CompletedProcess([], 0, "", "")


def _store(monkeypatch: pytest.MonkeyPatch, server: _Store) -> list[list[str]]:
    packed: list[list[str]] = []

    def pack(root: Path, keys: list[str], out: Path) -> bool:
        packed.append(keys)
        out.write_bytes(b"tarball")
        return True

    monkeypatch.setattr(deploy_upload, "_pack", pack)
    monkeypatch.setattr(deploy_upload, "_run_remote_capture", server.remote)
    return packed


def test_only_the_files_the_server_lacks_are_sent_then_checked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Steward's first deploy brought the database and not one of the 92
    files its rows named (aegis-stack#1679)."""
    server = _Store((1, "\n".join(GONE)), (0, ""))
    packed = _store(monkeypatch, server)
    upload_storage(tmp_path, SERVER)
    assert packed == [GONE]
    check, unpack, recheck = server.calls
    assert f"tar -xzf - -C {STORAGE_ROOT}" in unpack
    assert server.uploaded == b"tarball"
    assert recheck == check


def test_a_file_neither_machine_has_fails_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    server = _Store((1, "\n".join(GONE)), (1, GONE[0]))
    _store(monkeypatch, server)
    with pytest.raises(typer.Exit):
        upload_storage(tmp_path, SERVER)
    assert GONE[0] in capsys.readouterr().err


def test_a_server_that_cannot_check_is_sent_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A project from before ``storage check``: Click's usage error, 2."""
    server = _Store((2, "No such command 'storage'."))
    packed = _store(monkeypatch, server)
    upload_storage(tmp_path, SERVER)
    assert packed == []
    assert len(server.calls) == 1


def test_the_pack_holds_the_keys_asked_for_that_this_store_has(
    tmp_path: Path,
) -> None:
    held, absent = GONE
    (tmp_path / held).parent.mkdir(parents=True)
    (tmp_path / held).write_bytes(b"kept")
    done = subprocess.run(
        ["sh", "-c", deploy_upload._PACK.replace(STORAGE_ROOT, str(tmp_path))],
        input=f"{held}\n{absent}\n".encode(),
        capture_output=True,
        # The real one runs in the container; macOS tar adds ._ files.
        env={**os.environ, "COPYFILE_DISABLE": "1"},
    )
    assert done.returncode == 0, done.stderr
    (tmp_path / "out.tar.gz").write_bytes(done.stdout)
    with tarfile.open(tmp_path / "out.tar.gz") as archive:
        assert archive.getnames() == [held]
