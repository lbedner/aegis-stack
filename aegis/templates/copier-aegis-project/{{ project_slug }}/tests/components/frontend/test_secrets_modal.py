"""The Flet Secrets modal: every declared credential through the secrets
API, a paste field for each one this app may set, and never a value on
screen. Writes go through the API, which holds the admin check."""

from types import SimpleNamespace
from typing import Any

import flet as ft
import pytest

from app.components.frontend.dashboard.modals import secrets_modal
from app.components.frontend.dashboard.modals.secrets_modal import SecretsSection
from tests.components.frontend._fakes import FakePage
from tests.components.frontend._tree import texts, walk

ROWS = [
    {"name": "OPENAI_API_KEY", "owner": "AI", "label": "", "secret": True,
     "source": "env", "hint": "wxyz", "set_at": None, "set_by": None,
     "needed": True, "verifiable": True},
    {"name": "ANTHROPIC_API_KEY", "owner": "AI", "label": "", "secret": True,
     "source": "database", "hint": "abcd", "set_at": None, "set_by": "ops@example.com",
     "needed": False, "verifiable": True},
    {"name": "GROQ_API_KEY", "owner": "AI", "label": "", "secret": True,
     "source": None, "hint": None, "set_at": None, "set_by": None,
     "needed": False, "verifiable": True},
    {"name": "RESEND_API_KEY", "owner": "Email", "label": "", "secret": True,
     "source": None, "hint": None, "set_at": None, "set_by": None,
     "needed": True, "verifiable": True},
]  # fmt: skip
VERIFIED = {"result": "verified", "message": "It works."}


class FakeAPI:
    def __init__(self, list_status: int = 200) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.list_status = list_status
        self.put_answer: tuple[int, Any] = (200, {**ROWS[1], "check": VERIFIED})

    async def request_with_status(
        self, method: str, endpoint: str, json: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        self.calls.append((method, endpoint, json))
        if method == "GET":
            return self.list_status, ROWS if self.list_status == 200 else None
        if method == "PUT":
            return self.put_answer
        if endpoint.endswith("/test"):
            return 200, VERIFIED
        return 204, None


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI()
    monkeypatch.setattr(
        secrets_modal,
        "get_session_state",
        lambda page: SimpleNamespace(api_client=fake),
    )
    return fake


SNACKS: list[ft.Control] = []


async def _section(writable: bool = True) -> SecretsSection:
    page = FakePage()
    SNACKS.clear()
    page.open = SNACKS.append  # type: ignore[attr-defined]  # snack bars
    section = SecretsSection(page, writable=writable)  # type: ignore[arg-type]
    await section.load()
    return section


def _fields(section: SecretsSection) -> dict[str, ft.TextField]:
    return {str(c.data): c for c in walk(section) if isinstance(c, ft.TextField)}


async def test_a_paste_field_only_where_the_app_may_set_it(api: FakeAPI) -> None:
    fields = _fields(await _section())
    assert set(fields) == {"ANTHROPIC_API_KEY", "GROQ_API_KEY", "RESEND_API_KEY"}
    assert all(f.password and not f.value for f in fields.values())


async def test_a_key_in_env_says_where_to_change_it(api: FakeAPI) -> None:
    assert any("change it in .env" in t.lower() for t in texts(await _section()))


async def test_saving_puts_the_value_and_clears_the_field(api: FakeAPI) -> None:
    section = await _section()
    field = _fields(section)["RESEND_API_KEY"]
    field.value = "re_live_0123456789"
    await section.save("RESEND_API_KEY")
    assert (
        "PUT",
        "/api/v1/secrets/RESEND_API_KEY",
        {"value": "re_live_0123456789"},
    ) in api.calls
    assert "re_live_0123456789" not in texts(section)
    assert not _fields(section)["RESEND_API_KEY"].value


async def test_remove_deletes_the_stored_value(api: FakeAPI) -> None:
    section = await _section()
    await section.remove("ANTHROPIC_API_KEY")
    assert ("DELETE", "/api/v1/secrets/ANTHROPIC_API_KEY", None) in api.calls


async def test_a_key_read_through_settings_gets_no_field(
    api: FakeAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ROWS[2], "live", False)
    section = await _section()
    assert "GROQ_API_KEY" not in _fields(section)
    assert any("Set it in .env" in t for t in texts(section))


async def test_read_only_shows_no_fields(api: FakeAPI) -> None:
    assert _fields(await _section(writable=False)) == {}


async def test_a_refused_list_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeAPI(list_status=403)
    monkeypatch.setattr(
        secrets_modal,
        "get_session_state",
        lambda page: SimpleNamespace(api_client=fake),
    )
    assert any("admin" in t.lower() for t in texts(await _section()))


def _said() -> str:
    return " ".join(" ".join(texts(snack)) for snack in SNACKS)


def _buttons(section: SecretsSection, label: str) -> list[Any]:
    return [c for c in walk(section) if getattr(c, "text", None) == label]


async def test_a_missing_needed_key_reads_apart_from_an_optional_one(
    api: FakeAPI,
) -> None:
    shown = texts(await _section())
    assert any("Missing" in t for t in shown)
    assert any("Not used" in t for t in shown)
    assert any("1 of 2 needed" in t for t in shown)


async def test_a_set_key_with_a_check_can_be_tested(api: FakeAPI) -> None:
    section = await _section()
    assert len(_buttons(section, "Test")) == 2  # the .env key and the stored one
    await section.test("OPENAI_API_KEY")
    assert ("POST", "/api/v1/secrets/OPENAI_API_KEY/test", None) in api.calls
    assert "It works." in _said()


async def test_a_saved_key_says_whether_it_was_verified(api: FakeAPI) -> None:
    section = await _section()
    _fields(section)["RESEND_API_KEY"].value = "re_live_0123456789"
    await section.save("RESEND_API_KEY")
    assert "verified" in _said()


async def test_a_refused_key_says_why(api: FakeAPI) -> None:
    api.put_answer = (
        422,
        {"detail": "RESEND_API_KEY was refused: api.resend.com refused it (401)."},
    )
    section = await _section()
    _fields(section)["RESEND_API_KEY"].value = "re_typo_0123456789"
    await section.save("RESEND_API_KEY")
    assert "refused" in _said()
