"""Overseer > Deployments: what is live (build, commit, when, health), the
host it runs on, and the database backups beside it (``ui_deployments``)."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import settings
from app.services.system import backup, health
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests._secret_settings import use_store
from tests.web.dom import one, select, text
from tests.web.overseer import page_html, sign_in, status_with

PAGE = "/overseer/deployments"


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    status = status_with()
    sign_in(app, monkeypatch, status)
    monkeypatch.setattr(health, "last_system_status", lambda: status)
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    use_runtime(monkeypatch, FakeRuntime(SERVER))
    _local(monkeypatch)
    return TestClient(app)


def _local(monkeypatch: pytest.MonkeyPatch) -> None:
    """No cloud metadata service in a test: this machine, no record."""
    from app.services.system import hosting

    async def local() -> dict[str, Any]:
        return {
            "key": None,
            "name": "Local",
            "logo": None,
            "facts": [],
            "console": None,
        }

    monkeypatch.setattr(hosting, "running_on", local)
    monkeypatch.setattr(hosting, "deploys_to", lambda: None)


def _facts(html: str, card: str) -> dict[str, str]:
    terms = select(html, f"#{card} dt")
    return {text(t): text(t.getnext()) for t in terms}


def test_the_sidebar_leads_to_deployment(client: TestClient) -> None:
    link = one(page_html(client, "/overseer"), f'#overseer-nav a[href="{PAGE}"]')
    assert text(link) == "Deployments"


def test_the_live_build_and_the_host(client: TestClient) -> None:
    """One card: the build, and the host it is on."""
    build = _facts(page_html(client, PAGE), "card-this-build")
    assert (build["Build"], build["Commit"], build["Health"]) == (
        "abc1234",
        "abc1234",
        "Healthy",
    )
    assert build["Live since"].endswith("(5 hours ago)")
    assert (build["CPUs"], build["Docker"]) == ("4", "27.1.1")


@pytest.mark.skipif(
    not hasattr(backup, "list_backups"), reason="no scheduled database backups"
)
def test_the_backups_newest_first(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "DATABASE_BACKUP_DIR", str(tmp_path))
    for stamp, age in (("20261001_020000", 48), ("20261003_020000", 3)):
        path = (
            tmp_path / f"{backup.BACKUP_FILE_PREFIX}{stamp}{backup.BACKUP_FILE_SUFFIX}"
        )
        path.write_bytes(b"x" * 2048)
        when = (datetime.now() - timedelta(hours=age)).timestamp()
        os.utime(path, (when, when))
    rows = select(page_html(client, f"{PAGE}/backups"), "#deployments-backups tbody tr")
    assert "20261003_020000" in text(rows[0]) and "3 hours ago" in text(rows[0])
    assert len(rows) == 2


def test_no_backups_says_why(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Without scheduled backups the page says so; with them, an empty volume.
    if hasattr(backup, "list_backups"):
        monkeypatch.setattr(settings, "DATABASE_BACKUP_DIR", str(tmp_path / "none"))
    note = text(one(page_html(client, f"{PAGE}/backups"), "#deployments-backups"))
    assert "backups" in note.lower()


def test_history_lists_what_else_was_done_to_the_server(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Below the deploys: each backup, upload, off-site copy and drill, who
    and from where, and how it went (aegis-stack#1482)."""
    from app.services.system import ui_deployments

    drill = {
        "kind": "restore-drill",
        "outcome": "failed",
        "summary": "files: 2 stored files missing",
        "finished_at": datetime.now(UTC) - timedelta(hours=3),
        "actor": "Ada <ada@example.org>",
        "origin": "ada-laptop",
    }

    async def recorded() -> dict[str, Any]:
        return ui_deployments.history_rows([], [drill])

    monkeypatch.setattr(ui_deployments, "history", recorded)
    (row,) = select(
        page_html(client, f"{PAGE}/history"), "#deployments-events tbody tr"
    )
    assert [text(td) for td in select(row, "td")] == [
        "Restore drill",
        "3 hours ago",
        "Ada <ada@example.org>",
        "ada-laptop",
        "Failed",
        "files: 2 stored files missing",
    ]


def test_the_history_section_lists_each_deploy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.system import ui_deployments

    async def recorded() -> dict[str, Any]:
        row = {
            "build": "aaa1111",
            "started": "2 hours ago",
            "by": "Ada",
            "from": "ada-laptop",
            "health": "passed",
            "backup": "",
            "rollback": "",
        }
        return {"rows": [row], "note": None}

    monkeypatch.setattr(ui_deployments, "history", recorded)
    (row,) = select(
        page_html(client, f"{PAGE}/history"), "#deployments-history tbody tr"
    )
    assert "aaa1111" in text(row) and "Ada" in text(row) and "passed" in text(row)


def test_it_shows_where_it_runs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider it runs on, with its facts and console, in the build's
    card."""
    from app.services.system import hosting

    running = {
        "key": "hetzner",
        "name": "Hetzner Cloud",
        "logo": "https://icons.example/hetzner.png",
        "facts": [("Location", "fsn1-dc14"), ("Server", "48211907")],
        "console": "https://console.hetzner.cloud/",
    }

    async def on_hetzner() -> dict[str, Any]:
        return running

    monkeypatch.setattr(hosting, "running_on", on_hetzner)
    monkeypatch.setattr(hosting, "deploys_to", lambda: None)
    html = page_html(client, PAGE)
    card = one(html, "#card-this-build")
    assert "Hetzner Cloud" in text(card) and "fsn1-dc14" in text(card)
    assert (
        one(card, 'a[href="https://console.hetzner.cloud/"]').get("target") == "_blank"
    )


# Off the server: only in a stack with the nightly off-site job (deploy,
# a database and the scheduler). Events stand in as plain objects, so the
# module still loads in a stack without the deploy_event table.
HOURS_AGO = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
COPY = SimpleNamespace(
    kind="offsite",
    outcome="ok",
    summary="Sent 20261016_020000: 3 copies kept, 117.7 MB in the bucket",
    finished_at=HOURS_AGO,
    detail={"stamp": "20261016_020000", "copies": 3, "bytes": 123456789},
)
DRILL = SimpleNamespace(
    kind="restore-drill",
    outcome="failed",
    summary="files: 2 stored files missing",
    finished_at=HOURS_AGO,
    detail={},
)


def _offsite_stack(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Skips without the job; its secrets store, and no backups."""
    pytest.importorskip("app.services.system.offsite")
    monkeypatch.setattr(settings, "DATABASE_BACKUP_DIR", str(tmp_path))
    return use_store(monkeypatch)


def _events(monkeypatch: pytest.MonkeyPatch, *found: Any) -> None:
    """The newest event of each kind is the one given."""
    from app.components.deploy import history

    async def latest_event(kind: str) -> Any:
        return next((e for e in found if e.kind == kind), None)

    monkeypatch.setattr(history, "latest_event", latest_event)


def _offsite_facts(client: TestClient) -> dict[str, str]:
    return _facts(page_html(client, f"{PAGE}/backups"), "card-offsite")


def test_off_the_server_says_how_to_set_it_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without a repository the backups live only beside the app."""
    _offsite_stack(monkeypatch, tmp_path)
    html = page_html(client, f"{PAGE}/backups")
    assert text(one(html, "#card-offsite p")).startswith("Not set up")
    assert one(html, "#card-offsite a").get("href") == "/overseer/secrets"


def test_off_the_server_shows_the_last_copy_and_the_last_drill(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """What the nightly job last did (its event): when, which backup, how
    many copies the bucket keeps and their size; or why it failed. And the
    last restore rehearsed."""
    store = _offsite_stack(monkeypatch, tmp_path)
    store.values["OFFSITE_BACKUP_REPOSITORY"] = "s3:https://example/b/app"
    _events(monkeypatch)
    html = page_html(client, f"{PAGE}/backups")
    assert text(one(html, "#card-offsite p")).startswith("No copy yet")
    _events(monkeypatch, COPY, DRILL)
    assert _offsite_facts(client) == {
        "Last copy": "3 hours ago",
        "Of": "20261016_020000",
        "Copies kept": "3",
        "In the bucket": "117.7 MB",
        "Restore rehearsed": "3 hours ago, failed: files: 2 stored files missing",
    }
    failed = SimpleNamespace(
        **{**vars(COPY), "outcome": "failed", "summary": "restic backup failed: no"}
    )
    _events(monkeypatch, failed)
    html = page_html(client, f"{PAGE}/backups")
    said = text(one(html, "#card-offsite p"))
    assert said == "The last copy failed: restic backup failed: no"
    assert _facts(html, "card-offsite") == {
        "Last copy": "3 hours ago",
        "Of": "20261016_020000",
        "Restore rehearsed": "Never",
    }


def test_a_copy_whose_size_restic_did_not_say_shows_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Not "0 B": the bucket is not empty because restic kept quiet."""
    store = _offsite_stack(monkeypatch, tmp_path)
    store.values["OFFSITE_BACKUP_REPOSITORY"] = "s3:https://e/b"
    unsized = SimpleNamespace(
        **{**vars(COPY), "detail": {**COPY.detail, "bytes": None}}
    )
    _events(monkeypatch, unsized)
    assert "In the bucket" not in _offsite_facts(client)
