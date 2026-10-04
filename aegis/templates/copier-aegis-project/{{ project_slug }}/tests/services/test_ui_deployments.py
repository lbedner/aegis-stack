"""What is deployed, as Overseer shows it in htmx and Flet alike
(``ui_deployments``): the live build and when it went live, the host it runs
on, and the database backups beside it."""

from datetime import datetime, timedelta
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.system import backup, health, ui_deployments
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime

has_backups = pytest.mark.skipif(
    not hasattr(backup, "list_backups"), reason="no scheduled database backups"
)


@pytest.fixture(autouse=True)
def healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    healthy = SimpleNamespace(overall_healthy=True)
    monkeypatch.setattr(health, "last_system_status", lambda: healthy)


async def test_the_live_build_its_commit_and_when_it_went_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    use_runtime(monkeypatch, FakeRuntime(SERVER))
    now = dict(await ui_deployments.now())
    assert (now["Build"], now["Commit"]) == ("abc1234", "abc1234")
    assert now["Live since"].endswith("(5 hours ago)")
    assert now["Health"] == "Healthy"


async def test_a_build_with_uncommitted_changes_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234-dirty-1759500000")
    use_runtime(monkeypatch, FakeRuntime(SERVER))
    now = dict(await ui_deployments.now())
    assert now["Commit"] == "abc1234, with uncommitted changes"


async def test_a_local_build_has_no_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BUILD_ID", "dev")
    use_runtime(monkeypatch, FakeRuntime(SERVER))
    now = dict(await ui_deployments.now())
    assert now["Build"] == "dev, not deployed" and "Commit" not in now


async def test_the_host_it_runs_on(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(SERVER))
    host = await ui_deployments.host()
    assert host["note"] is None
    facts = dict(host["facts"])
    assert facts["CPUs"] == "4"
    assert facts["Memory"] == "8.0 GB"
    assert facts["Disk"] == "60.0 GB of 100.0 GB used (60.0%)"
    assert facts["Docker"] == "27.1.1"


async def test_a_runtime_that_does_not_answer_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(SERVER, fail=True))
    host = await ui_deployments.host()
    assert host["facts"] == [] and "not answering" in host["note"]


def _backup(directory: Path, stamp: str, size: int, age: timedelta) -> None:
    path = directory / f"{backup.BACKUP_FILE_PREFIX}{stamp}{backup.BACKUP_FILE_SUFFIX}"
    path.write_bytes(b"x" * size)
    when = (datetime.now() - age).timestamp()
    os.utime(path, (when, when))


@has_backups
def test_the_backups_newest_first_with_size_and_age(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATABASE_BACKUP_DIR", str(tmp_path))
    _backup(tmp_path, "20261001_020000", 2048, timedelta(days=2))
    _backup(tmp_path, "20261003_020000", 4096, timedelta(hours=3))
    view = ui_deployments.backups()
    assert view["note"] is None
    assert [(r["size"], r["taken"]) for r in view["rows"]] == [
        ("4.0 KB", "3 hours ago"),
        ("2.0 KB", view["rows"][1]["taken"]),
    ]
    assert view["rows"][0]["name"].endswith(
        f"20261003_020000{backup.BACKUP_FILE_SUFFIX}"
    )


@has_backups
def test_no_backups_yet_says_where_they_go(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATABASE_BACKUP_DIR", str(tmp_path / "none"))
    view = ui_deployments.backups()
    assert view["rows"] == [] and str(tmp_path / "none") in view["note"]
