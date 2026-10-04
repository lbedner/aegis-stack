"""Overseer > Deployments: what is live (build, commit, when, health), the
host it runs on, and the database backups beside it (``ui_deployments``)."""

from datetime import datetime, timedelta
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.services.system import backup, health
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests.web.dom import one, select, text
from tests.web.overseer import sign_in, status_with

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


def _html(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.text


def _facts(html: str, card: str) -> dict[str, str]:
    terms = select(html, f"#{card} dt")
    return {text(t): text(t.getnext()) for t in terms}


def test_the_sidebar_leads_to_deployment(client: TestClient) -> None:
    link = one(_html(client, "/overseer"), f'#overseer-nav a[href="{PAGE}"]')
    assert text(link) == "Deployments"


def test_the_live_build_and_the_host(client: TestClient) -> None:
    html = _html(client, PAGE)
    now = _facts(html, "card-now")
    assert (now["Build"], now["Commit"], now["Health"]) == (
        "abc1234",
        "abc1234",
        "Healthy",
    )
    assert now["Live since"].endswith("(5 hours ago)")
    host = _facts(html, "card-host")
    assert (host["CPUs"], host["Docker"]) == ("4", "27.1.1")


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
    rows = select(_html(client, f"{PAGE}/backups"), "#deployments-backups tbody tr")
    assert "20261003_020000" in text(rows[0]) and "3 hours ago" in text(rows[0])
    assert len(rows) == 2


def test_no_backups_says_why(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Without scheduled backups the page says so; with them, an empty volume.
    if hasattr(backup, "list_backups"):
        monkeypatch.setattr(settings, "DATABASE_BACKUP_DIR", str(tmp_path / "none"))
    note = text(one(_html(client, f"{PAGE}/backups"), "#deployments-backups"))
    assert "backups" in note.lower()


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
    (row,) = select(_html(client, f"{PAGE}/history"), "#deployments-history tbody tr")
    assert "aaa1111" in text(row) and "Ada" in text(row) and "passed" in text(row)


def test_it_shows_where_it_runs_and_where_it_can(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider it runs on, with its facts and console, and every
    provider aegis knows as a card, the one in use marked."""
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
    html = _html(client, PAGE)
    card = one(html, "#card-running-on")
    assert "Hetzner Cloud" in text(card) and "fsn1-dc14" in text(card)
    assert (
        one(card, 'a[href="https://console.hetzner.cloud/"]').get("target") == "_blank"
    )
    tiles = select(html, "[data-provider]")
    assert [t.get("data-provider") for t in tiles] == [
        "hetzner",
        "digitalocean",
        "aws",
        "server",
    ]
    assert [
        t.get("data-provider") for t in select(html, "[data-provider][data-current]")
    ] == ["hetzner"]
    detail = one(html, '[data-provider-detail="hetzner"]')
    assert "aegis deploy-provision --provider hetzner" in text(detail)
    assert "HCLOUD_TOKEN" in text(detail)
