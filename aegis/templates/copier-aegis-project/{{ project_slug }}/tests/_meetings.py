"""The meeting bot's seams, for the tests that run it: its sessions, its
pace, and the call it opens; and the meetings those tests read."""

import base64
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.util import find_spec
from typing import Any
from uuid import uuid4

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings import service as meetings_service
from app.services.meetings.domains.actions import runs as action_runs
from app.services.meetings.domains.actions import tokens
from app.services.meetings.domains.bot import run as bot
from app.services.meetings.domains.bot import transcript
from app.services.meetings.domains.bot.audio import RATE
from app.services.meetings.domains.bot.login import CALENDAR, LOGIN
from app.services.meetings.domains.bot.meet import CallState
from app.services.meetings.domains.bot.row import transition, write_captions
from app.services.meetings.domains.moments import tidy
from app.services.meetings.domains.moments.service import moments_of
from app.services.meetings.domains.notes.service import keep_notes
from app.services.meetings.domains.people.kept import guides_of, keep_guide
from app.services.meetings.domains.series import service as series_service
from app.services.meetings.domains.series.kept import keep_series
from app.services.meetings.domains.series.queries import series_link
from app.services.meetings.models import (
    NOT_DONE,
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
    SeriesNotes,
)
from app.services.meetings.service import MeetingsService
from tests._secret_settings import use_store
from tests._session import opens

MEET = "https://meet.google.com/abc-defg-hij"
# Another owner than the one signed in. With auth, a meeting's owner is a
# user: 999 is one conftest seeds (``KNOWN_OWNER_IDS``).
THEIRS = 999
# The smallest PNG there is, one transparent pixel: an agent's picture.
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
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
    themes: Callable[[int], Awaitable[None]] | None = None,
) -> None:
    """The bot runs on ``session`` and joins ``call`` instead of a browser,
    beating on every look, and she has no live voice in the call."""

    @asynccontextmanager
    async def her_live(
        call: Any, voice: Any, engine: Any, owner: int | None
    ) -> AsyncIterator[Any]:
        yield None

    monkeypatch.setattr(bot, "live", her_live)
    monkeypatch.setattr(bot, "get_async_session", opens(session))
    monkeypatch.setattr(bot, "POLL_SECONDS", poll_seconds)
    monkeypatch.setattr(bot, "BEAT_SECONDS", 0)
    monkeypatch.setattr(transcript, "BEAT_SECONDS", 0)
    # No model writes the notes unless the test brings one.
    monkeypatch.setattr(bot, "notes_writer", lambda: notes)
    monkeypatch.setattr(bot, "guides_writer", lambda: guides)
    monkeypatch.setattr(bot, "themes_writer", lambda: themes)

    @asynccontextmanager
    async def open_meet(
        url: str,
        on_audio: Callable[[str], None] | None = None,
        login: str = LOGIN,
        start: Any = None,
    ) -> AsyncIterator[Any]:
        call.on_audio, call.login, call.start = on_audio, login, start
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


def hold_the_cleaner(monkeypatch: pytest.MonkeyPatch) -> tuple[list[int], list[Any]]:
    """A question clean-up that only says which meetings it cleaned (done
    with ``CLEANING`` after, as ``clean_up`` is), its runs held rather than
    started, and none being cleaned yet: the meetings cleaned, and the runs
    to await."""
    cleaned: list[int] = []

    async def clean(meeting_id: int) -> None:
        cleaned.append(meeting_id)
        tidy.CLEANING.discard(meeting_id)

    runs: list[Any] = []
    monkeypatch.setattr(tidy, "cleaner", lambda: clean)
    monkeypatch.setattr(tidy, "background", runs.append)
    monkeypatch.setattr(tidy, "CLEANING", set())
    return cleaned, runs


def hold_the_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A line put to the bot asks her answer as it is said: held here, never
    run (no model is called)."""
    monkeypatch.setattr(action_runs, "background", lambda work: work.close())


class FakeCall:
    """A call whose states are scripted: one per look, the last repeating.
    ``during`` runs a hook at a named moment, as another process would."""

    def __init__(
        self,
        states: list[CallState],
        people: list[int] | None = None,
        during: dict[str, Callable[[], Any]] | None = None,
        captions: list[list[Caption]] | None = None,
        sound: bool = False,
    ):
        self.states = states
        self.counts = people or [3]
        self.shown = captions or [[]]
        self.captions_on = False
        self.during = during or {}
        self.said: list[str] = []
        self.asked_as: str | None = None
        self.left = False
        # A second of the call reaches the bot on every look, while ``sound``.
        self.sound = sound
        self.on_audio: Callable[[str], None] | None = None
        # What its camera showed (each change) and what it said aloud.
        self.cards: list[dict[str, Any]] = []
        self.spoken: list[bytes] = []
        self.captions_offered = True

    async def _at(self, moment: str) -> None:
        if moment in self.during:
            await self.during[moment]()

    async def ask_to_join(self, bot_name: str) -> None:
        self.asked_as = bot_name
        await self._at("ask_to_join")

    async def state(self) -> CallState:
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    async def page_text(self) -> str:
        return ""

    async def people(self) -> int:
        return self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]

    async def say(self, text: str) -> None:
        self.said.append(text)
        await self._at("say")

    async def leave(self) -> None:
        self.left = True

    async def turn_on_captions(self) -> bool:
        self.captions_on = self.captions_offered
        return self.captions_offered

    async def show(self, **update: Any) -> None:
        self.cards.append(update)

    async def speak(self, audio: bytes) -> None:
        self.spoken.append(audio)

    async def captions(self) -> list[Caption]:
        if self.sound and self.on_audio is not None:
            self.on_audio(SECOND)
        return self.shown.pop(0) if len(self.shown) > 1 else self.shown[0]


class FakeLive:
    """Her live voice in a call, as the bot binds it (``actions.live.LIVE``):
    what it was asked, what it answers (or the error it raises), what it
    said aloud, and whether it is still open."""

    def __init__(
        self,
        said: str | Exception = "",
        *,
        spoken: tuple[str, ...] = (),
        open: bool = True,
    ) -> None:
        self.said, self.open = said, open
        self.asked: list[str] = []
        self.spoken = list(spoken)

    async def ask(self, text: str) -> str:
        self.asked.append(text)
        if isinstance(self.said, Exception):
            raise self.said
        self.spoken.append(self.said)
        return self.said

    def spoke(self, text: str) -> bool:
        return text in self.spoken


def hold_the_series_writer(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A series writer whose runs are held rather than started, and no
    series being written yet: the runs to await."""

    async def write(meeting_id: int) -> None:
        return None

    runs: list[Any] = []
    monkeypatch.setattr(series_service, "themes_writer", lambda: write)
    monkeypatch.setattr(series_service, "background", runs.append)
    monkeypatch.setattr(series_service, "THEMING", set())
    return runs


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
    session: AsyncSession,
    meeting_id: int,
    *lines: tuple[str, str],
    apart: float = 1.0,
    at: Sequence[float] | None = None,
) -> list[int]:
    """``lines`` (speaker, text) as the meeting's transcript, ``apart``
    seconds apart (or at the seconds ``at`` names), the way the bot keeps
    captions; their row ids, in order."""
    rows: dict[str, int] = {}
    for n, (speaker, text) in enumerate(lines):
        when = at[n] if at is not None else n * apart
        caption = Caption(str(n), speaker, text)
        await write_captions(
            session, meeting_id, [caption], rows, when, {caption.line: when}
        )
    return [rows[str(n)] for n in range(len(lines))]


async def a_runner_looked_in(session: AsyncSession) -> None:
    """A runner for every owner has just asked for runs: one is running."""
    _, value = await tokens.create(session, None, "laptop")
    await tokens.resolve(session, value)


async def ended(
    session: AsyncSession,
    owner: int | None,
    *lines: tuple[str, str],
    notes: Callable[[list[int]], Notes],
    url: str = MEET,
) -> tuple[int, list[int]]:
    """A meeting of ``owner``'s on ``url`` the bot has left, having heard
    ``lines``, with the notes ``notes`` writes from their row ids. Returns
    its id and those ids."""
    meeting = await MeetingsService(session, owner).request(url, "Notes")
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


async def asked_twice(
    session: AsyncSession, owner: int | None
) -> tuple[list[int], list[int]]:
    """Two of ``owner``'s meetings on one link where Dana asked for the
    usage report: the meetings, and the line she asked in each."""
    meetings, asked = [], []
    for said in ("The usage report?", "Still no report."):
        meeting_id, ids = await ended(
            session, owner, ("Dana", said), notes=lambda _: Notes(summary="-")
        )
        meetings.append(meeting_id)
        asked.append(ids[0])
    return meetings, asked


async def a_meeting(session: AsyncSession, owner: int | None = None) -> int:
    """A meeting of ``owner``'s the bot was just asked to join: its id."""
    meeting = await MeetingsService(session, owner).request(MEET, "Notes")
    return meeting.id  # type: ignore[return-value]


async def topic(session: AsyncSession, moment_ids: list[int], name: str) -> None:
    """These moments named one card's topic, as a clean-up names them
    (``tidy.keep_topics``)."""
    await tidy.keep_topics(
        session, {moment_ids[0]: moment_ids}, [(moment_ids[0], True, name)]
    )


async def asked_a_question(
    session: AsyncSession,
    owner: int | None = None,
    *,
    status: MeetingStatus | None = None,
    lines: Sequence[tuple[str, str]] = (
        ("Sam", "Let's talk about the beta."),
        ("Dana", "The usage report is late."),
        ("Dana", "Can the CSV export ship this week?"),
    ),
) -> tuple[int, int]:
    """One of ``owner``'s meetings where, after some talk, Dana asks whether
    the CSV export can ship this week (or the one moment ``lines`` say;
    moved to ``status``, when given): its id and the moment's id."""
    meeting_id = await a_meeting(session, owner)
    await said(session, meeting_id, *lines)
    if status is not None:
        await transition(session, meeting_id, status, from_=NOT_DONE)
    (moment,) = await moments_of(session, meeting_id)
    return meeting_id, moment.id


async def kept_series(
    session: AsyncSession,
    owner: int | None,
    url: str = MEET,
    name: str = "",
    **content: Any,
) -> int:
    """The series of ``owner``'s meetings on ``url``, kept as the model
    would have written it (``content`` as ``SeriesNotes``' parts); its id."""
    notes = SeriesNotes(**({"summary": "Over time."} | content))
    return await keep_series(
        session,
        owner,
        series_link(url),
        notes,
        name=name,
        model_name="test-model",
        meetings=2,
    )


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
