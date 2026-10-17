"""The nightly backup, copied off the server with restic (#519).

A stand-in ``restic`` on ``PATH`` records each call and the repository
settings it was handed; the job's own logic (what it sends, in what
order, what it refuses) runs for real.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

import pytest

from app.components.deploy import history
from app.core.config import settings
from app.services.system import offsite
from tests._deploy_events import no_deploy_events  # noqa: F401
from tests._secret_settings import FakeStore, use_store

pytestmark = pytest.mark.usefixtures("no_deploy_events")

SET_UP = {
    "OFFSITE_BACKUP_REPOSITORY": "s3:https://nyc3.digitaloceanspaces.com/b/app",
    "OFFSITE_BACKUP_PASSWORD": "a long password",
    "OFFSITE_BACKUP_ACCESS_KEY": "DO00ACCESS",
    "OFFSITE_BACKUP_SECRET_KEY": "secret",
}
FAKE_RESTIC = """#!/bin/sh
python3 - "$@" <<'EOF'
import json, os, sys
with open(os.environ["RESTIC_CALLS"], "a") as log:
    log.write(json.dumps({
        "args": sys.argv[1:],
        "repository": os.environ.get("RESTIC_REPOSITORY"),
        "password": os.environ.get("RESTIC_PASSWORD"),
        "key": os.environ.get("AWS_ACCESS_KEY_ID"),
        "secret": os.environ.get("AWS_SECRET_ACCESS_KEY"),
    }) + "\\n")
EOF
case "$1 $2" in
  "cat config") [ -n "$RESTIC_INITIALISED" ] || exit 1 ;;
  backup*) [ -z "$RESTIC_FAILS" ] || { echo "Fatal: unable to open repository" >&2; exit 1; } ;;
  snapshots*) echo '[{"id": "a"}, {"id": "b"}, {"id": "c"}]' ;;
  stats*) echo '{"total_size": 123456789}' ;;
esac
"""


@pytest.fixture
def restic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in restic first on PATH; the calls it was given land in the
    returned file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "restic").write_text(FAKE_RESTIC)
    (bin_dir / "restic").chmod(stat.S_IRWXU)
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("RESTIC_CALLS", str(calls))
    return calls


@pytest.fixture
def backups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two nights of the 02:00 backup, the newer one last written."""
    directory = tmp_path / "backups"
    directory.mkdir()
    for night in ("20261015_020000", "20261016_020000"):
        (directory / f"database_backup_{night}.db").write_bytes(b"SQLite")
        (directory / f"storage_backup_{night}.tar").write_bytes(b"tar")
    newer = directory / "database_backup_20261016_020000.db"
    os.utime(newer, (newer.stat().st_atime, newer.stat().st_mtime + 60))
    monkeypatch.setattr(settings, "DATABASE_BACKUP_DIR", str(directory))
    return directory


def _calls(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _set_up(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    store = use_store(monkeypatch)
    store.values.update(SET_UP)
    return store


async def test_without_a_repository_nothing_is_sent(
    restic: Path, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch)
    await offsite.offsite_backup_job()
    assert _calls(restic) == []


async def test_the_newest_backup_is_sent_then_old_copies_thinned(
    restic: Path, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first run makes the repository; restic gets the bucket and its
    password from the store, never from the server's environment."""
    _set_up(monkeypatch)
    await offsite.offsite_backup_job()
    calls = _calls(restic)
    assert [c["args"][:2] for c in calls] == [
        ["cat", "config"],
        ["init"],
        ["backup", "--tag"],
        ["forget", "--keep-daily"],
        ["snapshots", "--json"],
        ["stats", "--mode"],
    ]
    sent = calls[2]["args"]
    assert sent[2] == "20261016_020000"
    assert sorted(Path(p).name for p in sent[3:]) == [
        "database_backup_20261016_020000.db",
        "storage_backup_20261016_020000.tar",
    ]
    assert calls[3]["args"][-1] == "--prune"
    assert {c["repository"] for c in calls} == {SET_UP["OFFSITE_BACKUP_REPOSITORY"]}
    assert {c["password"] for c in calls} == {SET_UP["OFFSITE_BACKUP_PASSWORD"]}
    assert {(c["key"], c["secret"]) for c in calls} == {("DO00ACCESS", "secret")}
    copy = await history.latest_event("offsite")
    assert copy is not None and copy.outcome == "ok"
    assert copy.detail == {"stamp": "20261016_020000", "copies": 3, "bytes": 123456789}
    assert copy.summary == "Sent 20261016_020000: 3 copies kept, 117.7 MB in the bucket"


async def test_a_repository_that_exists_is_not_made_again(
    restic: Path, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_up(monkeypatch)
    monkeypatch.setenv("RESTIC_INITIALISED", "1")
    await offsite.offsite_backup_job()
    assert "init" not in [c["args"][0] for c in _calls(restic)]


async def test_a_failed_send_fails_the_job_saying_why(
    restic: Path, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scheduler's history shows it; old copies are not thinned after
    a night that sent nothing."""
    _set_up(monkeypatch)
    monkeypatch.setenv("RESTIC_FAILS", "1")
    with pytest.raises(RuntimeError, match="unable to open repository"):
        await offsite.offsite_backup_job()
    assert "forget" not in [c["args"][0] for c in _calls(restic)]
    copy = await history.latest_event("offsite")
    assert copy is not None and copy.outcome == "failed"
    assert "unable to open repository" in copy.summary


async def test_half_set_up_fails_naming_what_is_missing(
    restic: Path, backups: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _set_up(monkeypatch)
    del store.values["OFFSITE_BACKUP_PASSWORD"]
    with pytest.raises(RuntimeError, match="OFFSITE_BACKUP_PASSWORD"):
        await offsite.offsite_backup_job()
    assert _calls(restic) == []


def test_each_value_can_come_from_the_env_file() -> None:
    """Settings reads only the ``.env`` keys it declares, and the server's
    ``.env`` (from ``.env.deploy``) is where these come from: undeclared,
    they reached it and the job said "not set up"."""
    from app.core.config import Settings

    assert set(offsite.RESTIC_ENV) <= set(Settings.model_fields)
