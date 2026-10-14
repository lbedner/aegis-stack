"""The meeting bot's seams, for the tests that run it: its sessions, its
pace, and the call it opens; and the meetings those tests read."""

import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings import bot
from app.services.meetings import service as meetings_service
from app.services.meetings.audio import RATE
from app.services.meetings.models import (
    ActionItem,
    Caption,
    Guide,
    Meeting,
    MeetingNotes,
    MeetingRecord,
    MeetingStatus,
    Notes,
    PersonGuide,
    Platform,
)
from app.services.meetings.service import (
    NOT_DONE,
    MeetingsService,
    save_notes,
    transition,
    write_captions,
)
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
        url: str, on_audio: Callable[[str], None] | None = None
    ) -> AsyncIterator[Any]:
        call.on_audio = on_audio
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
    content = notes(ids).model_dump()
    await save_notes(session, MeetingNotes(meeting_id=meeting_id, content=content))
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


async def kept_guide(
    session: AsyncSession, owner: int | None, person: str, **content: Any
) -> int:
    """A guide to ``person`` for ``owner``, kept as the model would have
    written it (``content`` as ``Guide``'s parts), from one meeting; its id."""
    guide = PersonGuide(
        owner_user_id=owner,
        person=person,
        content=Guide(**content).model_dump(),
        meetings=1,
        model_name="test-model",
    )
    session.add(guide)
    await session.commit()
    return guide.id  # type: ignore[return-value]


def record(meeting: Meeting | None = None, **fields: Any) -> MeetingRecord:
    """A meeting read in full, as ``MeetingsService.read`` returns it: one
    the bot has left, Ada heard for 42 s, ``fields`` over that."""
    meeting = meeting or Meeting(
        id=7,
        url=MEET,
        platform=Platform.MEET,
        status=MeetingStatus.LEFT,
        bot_name="Notes",
        heard={"Ada": 42.0},
    )
    read: dict[str, Any] = {
        "notes": None,
        "notes_error": None,
        "model_name": None,
        "transcript": [],
        "status": "Left",
        "length": "30:30",
        "heard": "Ada 42s",
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
