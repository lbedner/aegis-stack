"""The bot's Google accounts, agents to the people who use them
(``domains.accounts``): each its own name in the call and its own sign-in,
kept under its own secret. A stack from before them keeps working: its one
sign-in becomes the first agent's, and its meetings that agent's."""

from collections.abc import Callable
import json
import time
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import secrets
from app.services.meetings.domains.accounts import service as accounts
from app.services.meetings.domains.bot import run as bot
from app.services.meetings.domains.bot.login import LOGIN
from app.services.meetings.domains.bot.meet import CallState
from app.services.meetings.models import MeetingStatus
from app.services.meetings.service import DEFAULT_BOT_NAME, MeetingsService, transition
from tests._meetings import MEET, PIXEL_PNG, bot_on, hold_the_bot, signed_in_state
from tests._secret_settings import FakeStore, use_store


async def test_a_stack_from_before_agents_keeps_its_bot(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its one sign-in is the first agent's, with no step to take, and
    every meeting it already had is that agent's."""
    store = use_store(monkeypatch)
    store.values[LOGIN] = json.dumps(signed_in_state())
    old = await MeetingsService(async_db_session, None).request(MEET)

    [first] = await accounts.agents(async_db_session)

    assert first.name == accounts.DEFAULT_AGENT
    assert first.display_name == DEFAULT_BOT_NAME
    assert first.login_secret == LOGIN
    await async_db_session.refresh(old)
    assert old.account_id == first.id
    [row] = await accounts.overview(async_db_session)
    assert row.sign_in == accounts.SIGNED_IN
    assert await accounts.agents(async_db_session) == [first]


async def test_each_agent_keeps_its_sign_in_apart(
    async_db_session: AsyncSession,
) -> None:
    work = await accounts.keep_agent(
        async_db_session, "work", "Work Notes", "notes@work.example"
    )

    assert work.login_secret == f"{LOGIN}__WORK"
    assert work.email == "notes@work.example"
    names = [a.name for a in await accounts.agents(async_db_session)]
    assert names == [accounts.DEFAULT_AGENT, "work"]
    again = await accounts.keep_agent(async_db_session, "work", None, None)
    assert again.id == work.id and again.display_name == "Work Notes"


@pytest.mark.parametrize("name", ["Work", "a b", "-work", "x" * 41, ""])
async def test_an_agent_is_named_so_it_can_be_typed(
    async_db_session: AsyncSession, name: str
) -> None:
    with pytest.raises(accounts.AgentNameError):
        await accounts.keep_agent(async_db_session, name, None, None)


async def test_sending_picks_the_default_unless_told(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    hold_the_bot(monkeypatch)
    svc = MeetingsService(async_db_session, None)
    work = await accounts.keep_agent(async_db_session, "work", "Work Notes", None)

    default = await bot.send_bot(svc, MEET, "")
    sent = await bot.send_bot(svc, MEET, "", agent="work")

    [first, _] = await accounts.agents(async_db_session)
    assert default.account_id == first.id and default.bot_name == DEFAULT_BOT_NAME
    assert sent.account_id == work.id and sent.bot_name == "Work Notes"
    with pytest.raises(accounts.AgentNotFoundError):
        await bot.send_bot(svc, MEET, "", agent="nobody")


async def test_the_bot_joins_with_its_agents_own_sign_in(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    hold_the_bot(monkeypatch)
    work = await accounts.keep_agent(async_db_session, "work", "Work Notes", None)
    svc = MeetingsService(async_db_session, None)
    meeting = await bot.send_bot(svc, MEET, "", agent="work")
    call = _Call()
    bot_on(monkeypatch, async_db_session, call)

    await bot.run_meeting(meeting.id)  # type: ignore[arg-type]

    assert call.login == work.login_secret
    assert call.asked_as == "Work Notes"


async def test_the_overview_says_whose_sign_in_works_and_where_each_is(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = use_store(monkeypatch)
    hold_the_bot(monkeypatch)
    work = await accounts.keep_agent(async_db_session, "work", "Work Notes", None)
    await accounts.keep_agent(async_db_session, "home", "Home Notes", None)
    store.values[LOGIN] = json.dumps(signed_in_state(expires=time.time() - 60))
    store.values[work.login_secret] = json.dumps(
        signed_in_state(expires=time.time() + 3600)
    )
    svc = MeetingsService(async_db_session, None)
    meeting = await bot.send_bot(svc, MEET, "", agent="work")
    await transition(
        async_db_session,
        meeting.id,  # type: ignore[arg-type]
        MeetingStatus.IN_CALL,
        from_=(MeetingStatus.REQUESTED,),
    )

    rows = {row.account.name: row for row in await accounts.overview(async_db_session)}

    assert rows[accounts.DEFAULT_AGENT].sign_in == accounts.SIGNED_OUT
    assert rows["work"].sign_in == accounts.SIGNED_IN
    assert rows["home"].sign_in == accounts.NOT_SIGNED_IN
    assert rows["work"].in_now == [meeting.id]
    assert rows["home"].in_now == []


class _Torn(FakeStore):
    """A store with one row that will not decrypt: reading it, alone or
    with others, raises as the secrets component's does."""

    def __init__(self, torn: str) -> None:
        super().__init__()
        self.torn = torn

    async def get(self, name: str) -> str | None:
        return (await self.get_many([name]))[name]

    async def get_many(self, names: list[str]) -> dict[str, str | None]:
        if self.torn in names:
            raise secrets.SecretUnreadableError(f"{self.torn} will not decrypt")
        return await super().get_many(names)


async def test_a_broken_sign_in_is_said_and_the_rest_still_show(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not JSON, not a sign-in, or a row that will not decrypt: each is
    Unreadable, and every other agent still says how it is."""
    work = await accounts.keep_agent(async_db_session, "work", None, None)
    home = await accounts.keep_agent(async_db_session, "home", None, None)
    away = await accounts.keep_agent(async_db_session, "away", None, None)
    store = _Torn(away.login_secret)
    monkeypatch.setattr(secrets, "_store", store)
    monkeypatch.setattr(secrets, "_discovered", True)
    store.values[LOGIN] = "{not json"
    store.values[work.login_secret] = json.dumps({"origins": []})
    store.values[home.login_secret] = json.dumps(signed_in_state())

    rows = {row.account.name: row for row in await accounts.overview(async_db_session)}

    assert rows[accounts.DEFAULT_AGENT].sign_in == accounts.UNREADABLE
    assert rows["work"].sign_in == accounts.UNREADABLE
    assert rows["away"].sign_in == accounts.UNREADABLE
    assert rows["home"].sign_in == accounts.SIGNED_IN


class _Call:
    """A call that lets the bot in and ends: who it was asked to join as,
    and the sign-in it was opened with."""

    def __init__(self) -> None:
        self.on_audio: Callable[[str], None] | None = None
        self.login: str | None = None
        self.asked_as: str | None = None
        self.states = [CallState.IN_CALL, CallState.ENDED]

    async def ask_to_join(self, bot_name: str) -> None:
        self.asked_as = bot_name

    async def state(self) -> CallState:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    async def say(self, text: str) -> None:
        return None

    async def turn_on_captions(self, wait_ms: int = 0) -> bool:
        return True

    async def captions(self) -> list[Any]:
        return []

    async def people(self) -> int:
        return 2

    async def leave(self) -> None:
        return None


async def test_an_agent_keeps_its_image_and_whether_its_camera_is_on(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch)
    await accounts.set_image(
        async_db_session, accounts.DEFAULT_AGENT, PIXEL_PNG, "image/png"
    )
    await accounts.set_switch(async_db_session, accounts.DEFAULT_AGENT, "camera", False)
    await accounts.set_switch(
        async_db_session, accounts.DEFAULT_AGENT, "answers_anyone", False
    )

    [row] = await accounts.overview(async_db_session)
    kept = await accounts.image_named(async_db_session, accounts.DEFAULT_AGENT)

    assert row.image is not None and not row.account.camera
    assert not row.account.answers_anyone
    assert kept is not None and (kept.data, kept.content_type) == (
        PIXEL_PNG,
        "image/png",
    )
    await accounts.clear_image(async_db_session, accounts.DEFAULT_AGENT)
    assert await accounts.image_named(async_db_session, accounts.DEFAULT_AGENT) is None


async def test_a_new_picture_is_a_new_version(async_db_session: AsyncSession) -> None:
    """What the picture's address carries, so a browser keeps one until
    it changes."""

    async def version() -> object:
        [row] = await accounts.overview(async_db_session)
        return row.image

    await accounts.set_image(
        async_db_session, accounts.DEFAULT_AGENT, PIXEL_PNG, "image/png"
    )
    first = await version()
    await accounts.set_image(
        async_db_session, accounts.DEFAULT_AGENT, PIXEL_PNG, "image/gif"
    )

    assert await version() not in (None, first)
    kept = await accounts.image_named(async_db_session, accounts.DEFAULT_AGENT)
    assert kept is not None and kept.content_type == "image/gif"


async def test_an_image_is_one_a_browser_draws_and_small(
    async_db_session: AsyncSession,
) -> None:
    with pytest.raises(accounts.AgentImageError):
        await accounts.set_image(
            async_db_session, accounts.DEFAULT_AGENT, PIXEL_PNG, "application/pdf"
        )
    with pytest.raises(accounts.AgentImageError):
        too_big = b"x" * (accounts.MOST_IMAGE_BYTES + 1)
        await accounts.set_image(
            async_db_session, accounts.DEFAULT_AGENT, too_big, "image/png"
        )
