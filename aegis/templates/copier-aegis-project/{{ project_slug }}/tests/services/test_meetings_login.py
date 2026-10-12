"""The bot's Google sign-in (``meetings.login``): kept as a secret, and put
on the browser the bot joins with, so Meet lets it in as that account."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from typing import Any

import pytest

from app.cli import meetings as meetings_cli
from app.core.config import settings
from app.services.meetings import meet
from app.services.meetings.login import LOGIN, signed_in
from tests._cli import invoke
from tests._meetings import MEET
from tests._secret_settings import use_store

STATE = {
    "cookies": [{"name": "SID", "value": "x", "domain": ".google.com", "path": "/"}],
    "origins": [],
}


class FakeBrowser:
    """The browser, its context and its page in one: what each was given."""

    def __init__(self) -> None:
        self.storage_state: Any = "never asked"
        self.visited: list[str] = []

    async def new_context(self, storage_state: Any = None) -> "FakeBrowser":
        self.storage_state = storage_state
        return self

    async def new_page(self) -> "FakeBrowser":
        return self

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.visited.append(url)


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> FakeBrowser:
    fake = FakeBrowser()

    @asynccontextmanager
    async def connect(args: list[str]) -> AsyncIterator[FakeBrowser]:
        yield fake

    monkeypatch.setattr(meet, "connect", connect)
    return fake


@pytest.mark.parametrize("state", [STATE, None], ids=["signed-in", "guest"])
async def test_the_bot_joins_with_the_stored_login_if_any(
    state: dict[str, Any] | None,
    browser: FakeBrowser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = use_store(monkeypatch)
    if state:
        store.values[LOGIN] = json.dumps(state)

    async with meet.open_meet(MEET):
        pass

    assert browser.storage_state == state
    assert browser.visited == [MEET]


def test_only_a_google_session_counts_as_signed_in() -> None:
    """Chrome closed before the sign-in finished keeps Google's visitor
    cookies, never its session one: nothing worth keeping."""
    visitor = {"name": "NID", "value": "x", "domain": ".google.com", "path": "/"}

    assert signed_in(STATE)
    assert not signed_in({"cookies": [visitor], "origins": []})


def test_login_keeps_the_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    store = use_store(monkeypatch)

    async def signed_in_chrome(chrome: str) -> dict[str, Any]:
        return STATE

    monkeypatch.setattr(meetings_cli, "capture_login", signed_in_chrome)

    result = invoke(["meetings", "login", "--chrome", "chrome"])

    assert result.exit_code == 0, result.output
    assert json.loads(store.values[LOGIN]) == STATE


def test_a_sign_in_it_cannot_keep_is_refused_before_chrome_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set in .env, which wins: nobody is sent to sign in for nothing."""
    use_store(monkeypatch)
    monkeypatch.setitem(settings.__dict__, LOGIN, json.dumps(STATE))
    opened: list[str] = []

    async def chrome_opened(chrome: str) -> dict[str, Any]:
        opened.append(chrome)
        return STATE

    monkeypatch.setattr(meetings_cli, "capture_login", chrome_opened)

    result = invoke(["meetings", "login", "--chrome", "chrome"])

    assert result.exit_code == 1
    assert ".env" in result.output
    assert not opened
