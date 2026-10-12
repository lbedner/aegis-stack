"""The meeting bot's seams, for the tests that run it: its sessions, its
pace, and the call it opens."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings import bot
from tests._session import opens

MEET = "https://meet.google.com/abc-defg-hij"


def bot_on(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    call: Any,
    poll_seconds: float = 0,
) -> None:
    """The bot runs on ``session`` and joins ``call`` instead of a browser,
    beating on every look."""
    monkeypatch.setattr(bot, "get_async_session", opens(session))
    monkeypatch.setattr(bot, "POLL_SECONDS", poll_seconds)
    monkeypatch.setattr(bot, "BEAT_SECONDS", 0)

    @asynccontextmanager
    async def open_meet(url: str) -> AsyncIterator[Any]:
        yield call

    monkeypatch.setattr(bot, "open_meet", open_meet)
