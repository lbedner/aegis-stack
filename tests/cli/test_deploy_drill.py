"""Deploy events and the restore drill (aegis-stack#1482).

``recorded`` writes what a command did to the server through the app's
``deploy event``; the drill restores the newest off-site copy on this
machine and records whether the app's own checks pass. Docker, restic and
the server are stand-ins; what the commands decide runs for real.
"""

from __future__ import annotations

import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
import typer

from aegis.commands import deploy, deploy_drill
from aegis.commands.deploy import ACTOR_ENV, FAILED, recorded

SERVER = {"host": "h", "user": "u", "path": "/opt/app"}
SETTINGS = {
    "OFFSITE_BACKUP_REPOSITORY": "s3:https://nyc3.example/b/app",
    "OFFSITE_BACKUP_PASSWORD": "pw",
    "OFFSITE_BACKUP_ACCESS_KEY": "AK",
    "OFFSITE_BACKUP_SECRET_KEY": "SK",
    "ENCRYPTION_KEY": "the key",
}
SNAPSHOT = {"short_id": "4f2a9c1e", "time": "2026-10-17T02:30:05.1+00:00"}


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Each event sent to the server's ``deploy event``."""
    sent: list[dict[str, Any]] = []

    def app_deploy(root: Path, remote: Any, path: str, *argv: str) -> Any:
        assert argv[0] == "event"
        sent.append(json.loads(argv[1]))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(deploy, "app_deploy", app_deploy)
    monkeypatch.setattr(deploy, "_deployer", lambda root: "Ada <ada@example.org>")
    return sent


def test_a_command_that_finishes_is_recorded_done(
    tmp_path: Path, events: list[dict[str, Any]]
) -> None:
    with recorded(tmp_path, SERVER, "backup") as said:
        said["summary"] = "Backed up 2026-10-17_020000"
        said["detail"] = {"backup": "2026-10-17_020000"}
    (event,) = events
    assert (event["kind"], event["outcome"]) == ("backup", "ok")
    assert event["actor"] == "Ada <ada@example.org>"
    assert event["detail"] == {"backup": "2026-10-17_020000"}


def test_one_that_exits_failing_is_recorded_failed(
    tmp_path: Path, events: list[dict[str, Any]]
) -> None:
    with pytest.raises(typer.Exit), recorded(tmp_path, SERVER, "upload-db"):
        raise typer.Exit(1)
    (event,) = events
    assert (event["outcome"], event["summary"]) == ("failed", FAILED)


def test_asked_from_the_overseer_it_names_who_asked(
    tmp_path: Path, events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent hands the command the Overseer user (``ACTOR_ENV``); the
    git user is who ran it at a terminal."""
    monkeypatch.setenv(ACTOR_ENV, "leonard@example.org")
    with recorded(tmp_path, SERVER, "backup"):
        pass
    assert events[0]["actor"] == "leonard@example.org"


def _copy(scratch: Path, *, files: bool = True) -> None:
    """What ``restic restore`` leaves: the backup directory's absolute path
    under the target, a database snapshot and the documents archive."""
    backups = scratch / "data" / "backups"
    backups.mkdir(parents=True)
    (backups / "database_backup_20261017_020000.db").write_bytes(b"SQLite")
    if files:
        store = scratch / "src" / "storage" / "sha256"
        store.mkdir(parents=True)
        (store / "a").write_bytes(b"doc")
        with tarfile.open(backups / "storage_backup_20261017_020000.tar", "w") as tar:
            tar.add(scratch / "src" / "storage", arcname="storage")


def _drill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checks: list[dict[str, Any]]
) -> dict[str, Any]:
    """The drill with its settings, image, restic and checks stood in;
    what reached the checks."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(deploy_drill, "_settings", lambda root: SETTINGS)
    monkeypatch.setattr(deploy_drill, "_app_image", lambda root: "app:latest")
    monkeypatch.setattr(deploy_drill, "_empty", lambda scratch: None)

    def restic(scratch: str, env: dict[str, str], *args: str) -> str:
        seen.setdefault("restic", []).append(args[0])
        seen["env"] = env
        if args[0] == "snapshots":
            return json.dumps([SNAPSHOT])
        _copy(Path(scratch))
        return ""

    def check(root: Path, image: str, scratch: Path, database: Path, key: str) -> Any:
        seen["database"] = database.name
        seen["stored"] = sorted(p.name for p in (scratch / "storage").rglob("*"))
        seen["key"] = key
        return checks

    monkeypatch.setattr(deploy_drill, "_restic", restic)
    monkeypatch.setattr(deploy_drill, "_check", check)
    return seen


PASSED = [
    {"name": "database", "ok": True, "said": "integrity: ok"},
    {"name": "secrets", "ok": True, "said": "3 read"},
    {"name": "files", "ok": True, "said": "Every stored file present"},
]


def test_a_drill_that_passes_is_recorded_with_its_copy_and_checks(
    tmp_path: Path, events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _drill(monkeypatch, tmp_path, PASSED)
    deploy_drill.restore_drill(tmp_path, SERVER)
    assert seen["restic"] == ["snapshots", "restore"]
    assert seen["env"]["RESTIC_PASSWORD"] == "pw" and seen["key"] == "the key"
    assert seen["database"] == "database_backup_20261017_020000.db"
    assert seen["stored"] == ["a", "sha256"]
    (event,) = events
    assert (event["kind"], event["outcome"]) == ("restore-drill", "ok")
    assert event["summary"] == "Restored 4f2a9c1e (2026-10-17 02:30): 3 checks passed"
    assert event["detail"]["checks"] == PASSED


def test_a_check_that_fails_fails_the_drill_by_name(
    tmp_path: Path, events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = {"name": "files", "ok": False, "said": "2 stored files missing"}
    _drill(monkeypatch, tmp_path, [*PASSED[:2], missing])
    with pytest.raises(typer.Exit):
        deploy_drill.restore_drill(tmp_path, SERVER)
    (event,) = events
    assert event["outcome"] == "failed"
    assert event["summary"].endswith("files: 2 stored files missing")


def test_without_its_settings_it_says_which_and_records_why(
    tmp_path: Path, events: list[dict[str, Any]]
) -> None:
    (tmp_path / ".env.deploy").write_text("OFFSITE_BACKUP_REPOSITORY=s3:x\n")
    with pytest.raises(typer.Exit):
        deploy_drill.restore_drill(tmp_path, SERVER)
    (event,) = events
    assert event["outcome"] == "failed"
    assert "OFFSITE_BACKUP_PASSWORD" in event["summary"]
    assert "ENCRYPTION_KEY" in event["summary"]
