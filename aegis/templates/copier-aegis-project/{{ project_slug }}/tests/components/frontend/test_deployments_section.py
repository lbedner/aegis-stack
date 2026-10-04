"""Overseer > Deployments in Flet, from the header: the same live build,
host and backups as the htmx page (``ui_deployments``)."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.components.frontend.dashboard.modals.base_popup import BasePopup
from app.components.frontend.dashboard.modals.deployments_section import (
    DeploymentsPopup,
    DeploymentsSection,
)
from app.core.config import settings
from app.services.system import health, hosting
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests.components.frontend._tree import texts, walk


@pytest.fixture(autouse=True)
def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    healthy = SimpleNamespace(overall_healthy=True)
    monkeypatch.setattr(health, "last_system_status", lambda: healthy)
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    use_runtime(monkeypatch, FakeRuntime(SERVER))

    async def on_hetzner() -> dict[str, Any]:
        return {
            "key": "hetzner",
            "name": "Hetzner Cloud",
            "logo": None,
            "facts": [("Location", "fsn1-dc14")],
            "console": "https://console.hetzner.cloud/",
        }

    monkeypatch.setattr(hosting, "running_on", on_hetzner)
    monkeypatch.setattr(hosting, "deploys_to", lambda: None)


async def test_it_shows_the_live_build_the_host_and_the_backups() -> None:
    section = DeploymentsSection()
    await section.load()
    shown = texts(section)
    assert "abc1234" in shown and "27.1.1" in shown
    assert any("Backups" in t for t in shown)


def test_the_popup_holds_the_section() -> None:
    popup = DeploymentsPopup(page=MagicMock())
    assert any(isinstance(n, DeploymentsSection) for n in walk(popup))


def test_a_header_popup_opens_once_and_is_reused() -> None:
    page = MagicMock()
    page.overlay = []
    DeploymentsPopup.open_on(page)
    DeploymentsPopup.open_on(page)
    (popup,) = page.overlay
    assert isinstance(popup, BasePopup) and popup.visible


async def test_it_lists_each_deploy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.system import ui_deployments

    async def recorded() -> dict[str, Any]:
        row = dict.fromkeys(("by", "from", "backup", "rollback"), "") | {
            "build": "aaa1111",
            "started": "2 hours ago",
            "health": "passed",
        }
        return {"rows": [row], "note": None}

    monkeypatch.setattr(ui_deployments, "history", recorded)
    section = DeploymentsSection()
    await section.load()
    shown = texts(section)
    assert "History" in shown and "aaa1111" in shown


async def test_it_shows_where_it_runs_and_where_it_can() -> None:
    section = DeploymentsSection()
    await section.load()
    shown = texts(section)
    assert "Hetzner Cloud" in shown and "fsn1-dc14" in shown
    assert "You're here" in shown
    assert any("aegis deploy-provision --provider hetzner" in t for t in shown)
    assert "DigitalOcean" in shown
