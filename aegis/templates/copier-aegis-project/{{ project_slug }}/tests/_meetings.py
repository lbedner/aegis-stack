"""The meeting bot's seams, for the tests that run it: its sessions, its
pace, and the call it opens; and the meetings those tests read."""

import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings import bot
from app.services.meetings.audio import RATE
from app.services.meetings.models import Caption, MeetingNotes, MeetingStatus, Notes
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
) -> None:
    """The bot runs on ``session`` and joins ``call`` instead of a browser,
    beating on every look."""
    monkeypatch.setattr(bot, "get_async_session", opens(session))
    monkeypatch.setattr(bot, "POLL_SECONDS", poll_seconds)
    monkeypatch.setattr(bot, "BEAT_SECONDS", 0)
    # No model writes the notes unless the test brings one.
    monkeypatch.setattr(bot, "notes_writer", lambda: notes)

    @asynccontextmanager
    async def open_meet(
        url: str, on_audio: Callable[[str], None] | None = None
    ) -> AsyncIterator[Any]:
        call.on_audio = on_audio
        yield call

    monkeypatch.setattr(bot, "open_meet", open_meet)


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
