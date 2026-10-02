"""The Flet Email tab's sending domains: listed through the comms API with
their status, a Check per domain, and Add, which shows the DNS records to
create."""

from types import SimpleNamespace
from typing import Any

import flet as ft
import pytest

from app.components.frontend.dashboard.modals.comms_modal import (
    domains as domains_module,
)
from app.components.frontend.dashboard.modals.comms_modal.domains import DomainsSection
from tests.components.frontend._fakes import FakePage
from tests.components.frontend._tree import texts, walk

API = "/api/v1/comms/domains"


class FakeAPI:
    def __init__(self, list_status: int = 200) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.list_status = list_status

    async def request_with_status(
        self, method: str, endpoint: str, json: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        self.calls.append((method, endpoint, json))
        if method == "GET":
            if self.list_status != 200:
                return self.list_status, {"detail": "Resend: restricted key"}
            return 200, [
                {"name": "mail.example.com", "status": "pending", "verified": False}
            ]
        if endpoint.endswith("/check"):
            return 200, {
                "name": "mail.example.com",
                "status": "verified",
                "verified": True,
            }
        record = {
            "type": "TXT",
            "host": "resend._domainkey",
            "value": "p=MIGf",
            "priority": None,
        }
        return 200, {"domain": json["domain"], "records": [record]}


SNACKS: list[Any] = []


def _section(monkeypatch: pytest.MonkeyPatch, api: FakeAPI) -> DomainsSection:
    monkeypatch.setattr(
        domains_module,
        "get_session_state",
        lambda page: SimpleNamespace(api_client=api),
    )
    page = FakePage()
    SNACKS.clear()
    page.open = SNACKS.append  # type: ignore[attr-defined]
    return DomainsSection(page)  # type: ignore[arg-type]


async def test_lists_domains_with_their_status(monkeypatch: pytest.MonkeyPatch) -> None:
    section = _section(monkeypatch, FakeAPI())
    await section.load()
    shown = " ".join(texts(section))
    assert "mail.example.com" in shown and "pending" in shown.lower()


async def test_check_asks_and_says_the_status(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeAPI()
    section = _section(monkeypatch, api)
    await section.load()
    await section.check("mail.example.com")
    assert ("POST", f"{API}/mail.example.com/check", None) in api.calls
    assert "verified" in " ".join(" ".join(texts(s)) for s in SNACKS).lower()


async def test_adding_shows_the_records_to_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeAPI()
    section = _section(monkeypatch, api)
    await section.load()
    (field,) = [c for c in walk(section) if isinstance(c, ft.TextField)]
    field.value = "new.example.com"
    await section.add()
    assert ("POST", API, {"domain": "new.example.com"}) in api.calls
    shown = " ".join(texts(section))
    assert "resend._domainkey" in shown and "p=MIGf" in shown


async def test_a_list_resend_refuses_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    section = _section(monkeypatch, FakeAPI(list_status=502))
    await section.load()
    assert any("restricted" in t for t in texts(section))
