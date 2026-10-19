"""The meeting bot's seams, for the tests that run it: its sessions, its
pace, and the call it opens; and the meetings those tests read."""

import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.util import find_spec
from typing import Any
from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings import bot
from app.services.meetings import service as meetings_service
from app.services.meetings.audio import RATE
from app.services.meetings.domains.notes.service import keep_notes
from app.services.meetings.domains.people.kept import guides_of, keep_guide
from app.services.meetings.login import CALENDAR, LOGIN
from app.services.meetings.models import (
    ActionItem,
    Caption,
    Guide,
    Meeting,
    MeetingPerson,
    MeetingRecord,
    MeetingStatus,
    Notes,
    PersonGuide,
    Platform,
)
from app.services.meetings.service import (
    NOT_DONE,
    MeetingsService,
    transition,
    write_captions,
)
from tests._secret_settings import use_store
from tests._session import opens

MEET = "https://meet.google.com/abc-defg-hij"
# A second of someone talking, as the Meet page hands it to the bot.
SECOND = base64.b64encode(b"\x00\x40" * RATE).decode()
# William at 20:52 in a real call (SAID), then the same turn as Meet shows
# it a moment later (SHOWN): it keeps a long turn short on screen by
# trimming its start while it grows.
SAID = (
    "Yeah. Yeah, it's basically the every time she starts talking, they go "
    "hold on a second."
)
SHOWN = "every time she starts talking, they go hold on a second. Let me just"


def bot_on(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    call: Any,
    poll_seconds: float = 0,
    notes: Callable[[int], Awaitable[None]] | None = None,
    guides: Callable[[int], Awaitable[None]] | None = None,
) -> None:
    """The bot runs on ``session`` and joins ``call`` instead of a browser,
    beating on every look."""
    monkeypatch.setattr(bot, "get_async_session", opens(session))
    monkeypatch.setattr(bot, "POLL_SECONDS", poll_seconds)
    monkeypatch.setattr(bot, "BEAT_SECONDS", 0)
    # No model writes the notes unless the test brings one.
    monkeypatch.setattr(bot, "notes_writer", lambda: notes)
    monkeypatch.setattr(bot, "guides_writer", lambda: guides)

    @asynccontextmanager
    async def open_meet(
        url: str, on_audio: Callable[[str], None] | None = None, login: str = LOGIN
    ) -> AsyncIterator[Any]:
        call.on_audio, call.login = on_audio, login
        yield call

    monkeypatch.setattr(bot, "open_meet", open_meet)


def hold_the_bot(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The meetings the bot is sent to, without starting it."""
    ids: list[int] = []

    async def start_meeting(meeting_id: int) -> None:
        ids.append(meeting_id)

    monkeypatch.setattr(bot, "start_meeting", start_meeting)
    return ids


def hold_the_writer(monkeypatch: pytest.MonkeyPatch) -> tuple[list[int], list[Any]]:
    """A notes writer that only says which meetings it wrote, its runs held
    rather than started, and no notes being written yet: the meetings
    written, and the runs to await."""
    written: list[int] = []

    async def write(meeting_id: int) -> None:
        written.append(meeting_id)

    runs: list[Any] = []
    monkeypatch.setattr(meetings_service, "notes_writer", lambda: write)
    monkeypatch.setattr(meetings_service, "background", runs.append)
    monkeypatch.setattr(meetings_service, "WRITING", set())
    return written, runs


def answering(
    monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any] | Exception, row: Any = None
) -> list[str]:
    """The meetings' writers answer ``answer`` (or raise it) on pydantic-ai's
    ``TestModel``, as ``row`` (an ``AgentConfig``; none = no agent row, so
    the built-in prompt on the model in force). Returns the model asked,
    each time it was."""
    from pydantic_ai.models.test import TestModel

    from app.services.ai.domains.chat import agent_loader
    from app.services.ai.domains.llm import active_model, model_factory

    asked: list[str] = []

    async def model_for(config: Any, settings: Any) -> tuple[Any, str]:
        asked.append(config.model)
        if isinstance(answer, Exception):
            raise answer
        return TestModel(custom_output_args=answer), "test-model"

    async def resolve_agent(slug: str = "", **_: Any) -> Any:
        return row or agent_loader.default_agent_config()

    async def no_stored_selection(settings: Any) -> bool:
        return False

    monkeypatch.setattr(model_factory, "model_for", model_for)
    monkeypatch.setattr(agent_loader, "resolve_agent", resolve_agent)
    monkeypatch.setattr(active_model, "sync_from_db", no_stored_selection)
    return asked


async def said(
    session: AsyncSession, meeting_id: int, *lines: tuple[str, str]
) -> list[int]:
    """``lines`` (speaker, text) as the meeting's transcript, a second
    apart, the way the bot keeps captions; their row ids, in order."""
    rows: dict[str, int] = {}
    for at, (speaker, text) in enumerate(lines):
        caption = Caption(str(at), speaker, text)
        await write_captions(
            session, meeting_id, [caption], rows, float(at), {caption.line: float(at)}
        )
    return [rows[str(at)] for at in range(len(lines))]


async def ended(
    session: AsyncSession,
    owner: int | None,
    *lines: tuple[str, str],
    notes: Callable[[list[int]], Notes],
) -> tuple[int, list[int]]:
    """A meeting of ``owner``'s the bot has left, having heard ``lines``,
    with the notes ``notes`` writes from their row ids. Returns its id and
    those ids."""
    meeting = await MeetingsService(session, owner).request(MEET, "Notes")
    meeting_id: int = meeting.id  # type: ignore[assignment]
    await transition(session, meeting_id, MeetingStatus.LEFT, from_=NOT_DONE)
    ids = await said(session, meeting_id, *lines)
    await keep_notes(session, meeting_id, notes(ids), None)
    return meeting_id, ids


async def docs_meeting(session: AsyncSession, owner: int | None) -> int:
    """An owner's meeting the bot has left, where Ada said she would write
    the docs, and the notes give it to her."""
    meeting_id, _ = await ended(
        session,
        owner,
        ("Ada", "I'll write the docs."),
        notes=lambda _: Notes(
            summary="Docs.",
            action_items=[ActionItem(text="Write the docs", owner="Ada")],
        ),
    )
    return meeting_id


async def person_named(
    session: AsyncSession, owner: int | None, name: str
) -> MeetingPerson | None:
    """The owner's person called ``name``, if there is one."""
    query = select(MeetingPerson).where(
        MeetingPerson.name == name, MeetingPerson.owner_user_id == owner
    )
    return (await session.exec(query)).first()


async def person_id(session: AsyncSession, owner: int | None, name: str) -> int:
    """The id of the owner's person called ``name``."""
    found = await person_named(session, owner, name)
    assert found is not None
    return found.id  # type: ignore[return-value]


async def guide_of(session: AsyncSession, person: int) -> Guide | None:
    """The person's guide, read back; None while they have none."""
    query = select(PersonGuide).where(PersonGuide.person_id == person)
    row = (await session.exec(query)).first()
    if row is None:
        return None
    return (await guides_of(session, [row.id]))[row.id]  # type: ignore[index, list-item]


def signed_in_state(expires: float = -1) -> dict[str, Any]:
    """A Google sign-in as Playwright keeps it; -1 never expires."""
    cookie = {"name": "SID", "value": "x", "domain": ".google.com", "expires": expires}
    return {"cookies": [cookie], "origins": []}


async def kept_guide(
    session: AsyncSession, owner: int | None, person: str, **content: Any
) -> int:
    """A guide to ``person`` for ``owner`` (the person they are, made if no
    meeting made them yet), kept as the model would have written it
    (``content`` as ``Guide``'s parts), from one meeting; its id."""
    found = await person_named(session, owner, person)
    if found is None:
        found = MeetingPerson(owner_user_id=owner, name=person)
        session.add(found)
        await session.flush()
    person_id: int = found.id  # type: ignore[assignment]
    await keep_guide(session, person_id, Guide(**content), "test-model", meetings=1)
    guide = (
        await session.exec(
            select(PersonGuide).where(PersonGuide.person_id == person_id)
        )
    ).one()
    return guide.id  # type: ignore[return-value]


async def someone_else(session: AsyncSession) -> int:
    """An owner other than the one signed in: a user of their own where the
    stack has auth (a meeting's owner is one), any other number where it
    has not."""
    if find_spec("app.models.user") is None:
        return 4242
    from app.models.user import User

    user = User(email=f"someone.{uuid4().hex[:8]}@example.com", hashed_password="-")
    session.add(user)
    await session.flush()
    return user.id  # type: ignore[return-value]


def record(meeting: Meeting | None = None, **fields: Any) -> MeetingRecord:
    """A meeting read in full, as ``MeetingsService.read`` returns it: one
    the bot has left, Ada heard for 42 s, ``fields`` over that."""
    meeting = meeting or Meeting(
        id=7,
        url=MEET,
        platform=Platform.MEET,
        status=MeetingStatus.LEFT,
        bot_name="Notes",
    )
    read: dict[str, Any] = {
        "notes": None,
        "notes_error": None,
        "model_name": None,
        "transcript": [],
        "status": "Left",
        "length": "30:30",
        "heard": "Ada 42s",
        "heard_seconds": {"Ada": 42.0},
        "people": ["Ada"],
        "mine": [],
        "under_way": False,
        "writing": False,
        "can_leave": False,
        "can_delete": True,
        "can_write": True,
        "can_rewrite": False,
    }
    return MeetingRecord(meeting=meeting, **(read | fields))


# A week of a daily standup, the first time Monday 2026-10-19 at 9:00 in
# New York (13:00 UTC), with its organizer, one attendee and its Meet link.
STANDUP = f"""
UID:standup@google.com
DTSTART;TZID=America/New_York:20261019T090000
DTEND;TZID=America/New_York:20261019T091500
RRULE:FREQ=DAILY;COUNT=3
SUMMARY:Standup
ORGANIZER;CN=Dana:mailto:dana@example.com
ATTENDEE;CN=Leo;PARTSTAT=ACCEPTED:mailto:Leo@Example.com
X-GOOGLE-CONFERENCE:{MEET}
"""


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A moment in October 2026, UTC."""
    return datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


def feed(*events: str) -> str:
    """A calendar as Google's iCal feed has it, of ``events`` (each the
    lines inside one VEVENT)."""
    body = "".join(f"BEGIN:VEVENT\n{event.strip()}\nEND:VEVENT\n" for event in events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\n{body}END:VCALENDAR\n"


class Calendar:
    """An agent's calendar for a test: its address kept under ``secret``,
    reading as ``events`` until ``shows`` changes them, or raising what
    ``ics`` is set to."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *events: str, secret: str = CALENDAR
    ) -> None:
        use_store(monkeypatch).values[secret] = f"https://calendar/{secret}"
        self.ics: str | Exception = feed(*events)

    def shows(self, *events: str) -> None:
        self.ics = feed(*events)

    async def read(self, url: str) -> str:
        if isinstance(self.ics, Exception):
            raise self.ics
        return self.ics
