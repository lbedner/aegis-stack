"""The meeting bot's run: ask to join, wait to be admitted, say who it is,
stay until there is a reason to leave, and write each step on the meeting
row.

It runs inside whichever process starts it: the CLI waits for it
(``meetings join``), the app runs it with ``background`` (``start_meeting``)
and cancels it at shutdown, when it records itself as left. It writes the
row only through the service's ``transition`` and ``heartbeat``. Each step
opens its own short session, so an hour-long call holds no database
connection.
"""

import asyncio

from app.core.concurrency import background
from app.core.db import get_async_session
from app.core.log import logger
from app.services.meetings.meet import CallState, MeetPage, open_meet
from app.services.meetings.models import Caption, Meeting, MeetingStatus, Platform
from app.services.meetings.service import (
    NOT_DONE,
    STILL_WANTED,
    MeetingsService,
    heartbeat,
    transition,
    write_captions,
)

POLL_SECONDS = 2.0
ADMIT_TIMEOUT_SECONDS = 300.0
# How long the bot stays once everyone else has gone.
ALONE_SECONDS = 120.0
# How often the run beats and reads back its status: a leave request waits
# at most this long, and on SQLite each beat takes the write lock.
BEAT_SECONDS = 10.0


class _RunEnded(Exception):  # noqa: N818 - control flow, not an error
    """The run ends here, as ``status``; a row already done (failed by
    another process) keeps what it says."""

    def __init__(self, status: MeetingStatus, reason: str | None = None) -> None:
        self.status, self.reason = status, reason


class _Pulse:
    """The run's heartbeat, every ``BEAT_SECONDS``: False once the meeting
    is no longer one the run should be in (asked to leave, or failed by
    another process)."""

    def __init__(self, meeting_id: int) -> None:
        self.meeting_id = meeting_id
        self.last = float("-inf")

    async def still_wanted(self) -> bool:
        now = asyncio.get_running_loop().time()
        if now - self.last < BEAT_SECONDS:
            return True
        self.last = now
        async with get_async_session() as session:
            return await heartbeat(session, self.meeting_id) in STILL_WANTED


class _Transcript:
    """The call's captions as transcript lines, timed from when the bot got
    in. What changed is written every ``BEAT_SECONDS`` (each write takes
    SQLite's write lock), and what is left by ``flush`` on the way out."""

    def __init__(self, meeting_id: int) -> None:
        self.meeting_id = meeting_id
        self.started = self.written_at = asyncio.get_running_loop().time()
        self.rows: dict[str, int] = {}  # caption line -> transcript row
        self.seen: dict[str, str] = {}  # caption line -> its text, last look
        self.pending: dict[str, Caption] = {}

    async def take(self, captions: list[Caption]) -> None:
        for c in captions:
            if self.seen.get(c.line) != c.text:
                self.seen[c.line] = c.text
                self.pending[c.line] = c
        now = asyncio.get_running_loop().time()
        if now - self.written_at >= BEAT_SECONDS:
            await self.flush()

    async def flush(self) -> None:
        loop = asyncio.get_running_loop()
        self.written_at = loop.time()
        if not self.pending:
            return
        async with get_async_session() as session:
            await write_captions(
                session,
                self.meeting_id,
                list(self.pending.values()),
                self.rows,
                self.written_at - self.started,
            )
        self.pending = {}


async def _move(
    meeting_id: int,
    to: MeetingStatus,
    from_: tuple[MeetingStatus, ...],
    reason: str | None = None,
) -> bool:
    async with get_async_session() as session:
        return await transition(session, meeting_id, to, from_=from_, reason=reason)


async def _step(meeting_id: int, to: MeetingStatus, from_: MeetingStatus) -> None:
    """The next step, or the end of the run when the row moved elsewhere
    (a leave request: it leaves; a failure: it stays failed)."""
    if not await _move(meeting_id, to, (from_,)):
        raise _RunEnded(MeetingStatus.LEFT)


async def _admitted(call: MeetPage, pulse: _Pulse) -> None:
    """Back once the host lets the bot in; ends the run otherwise."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ADMIT_TIMEOUT_SECONDS
    while True:
        state = await call.state()
        if state == CallState.IN_CALL:
            return
        if state == CallState.REFUSED:
            raise _RunEnded(MeetingStatus.FAILED, "The host refused the bot's request")
        if state == CallState.ENDED or not await pulse.still_wanted():
            raise _RunEnded(MeetingStatus.LEFT)
        if loop.time() >= deadline:
            raise _RunEnded(
                MeetingStatus.FAILED,
                f"Nobody admitted the bot within {ADMIT_TIMEOUT_SECONDS:.0f} seconds",
            )
        await asyncio.sleep(POLL_SECONDS)


async def _stay(call: MeetPage, pulse: _Pulse, transcript: _Transcript) -> None:
    """Back when the bot should leave: asked to, or alone too long. Ends
    the run when the call ends on its own (any page but the call's). Each
    look keeps what was said since the last."""
    loop = asyncio.get_running_loop()
    alone_since: float | None = None
    try:
        while True:
            if await call.state() != CallState.IN_CALL:
                raise _RunEnded(MeetingStatus.LEFT)
            await transcript.take(await call.captions())
            if not await pulse.still_wanted():
                return
            people = await call.people()
            if people is None or people > 1:
                alone_since = None
            elif alone_since is None:
                alone_since = loop.time()
            elif loop.time() - alone_since >= ALONE_SECONDS:
                return
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await transcript.flush()


async def _join(meeting: Meeting) -> None:
    meeting_id: int = meeting.id  # type: ignore[assignment]
    await _step(meeting_id, MeetingStatus.JOINING, MeetingStatus.REQUESTED)
    pulse = _Pulse(meeting_id)
    async with open_meet(meeting.url) as call:
        if not await pulse.still_wanted():
            raise _RunEnded(MeetingStatus.LEFT)
        await call.ask_to_join(meeting.bot_name)
        await _step(meeting_id, MeetingStatus.WAITING, MeetingStatus.JOINING)
        await _admitted(call, pulse)
        await _step(meeting_id, MeetingStatus.IN_CALL, MeetingStatus.WAITING)
        transcript = _Transcript(meeting_id)
        await call.say(
            f"{meeting.bot_name} is taking notes in this meeting: "
            "what is said here is transcribed."
        )
        if not await call.turn_on_captions():
            logger.warning("No captions in this call", meeting_id=meeting_id)
        await _stay(call, pulse, transcript)
        await call.leave()


async def run_meeting(meeting_id: int) -> None:
    """Take the bot through one meeting, start to finish."""
    async with get_async_session() as session:
        meeting = await MeetingsService(session, None).get(meeting_id)
    try:
        if meeting.platform != Platform.MEET:
            raise _RunEnded(
                MeetingStatus.FAILED,
                f"The bot joins Google Meet so far, not {meeting.platform.title()}",
            )
        await _join(meeting)
        await _move(meeting_id, MeetingStatus.LEFT, NOT_DONE)
    except _RunEnded as ended:
        await _move(meeting_id, ended.status, NOT_DONE, ended.reason)
    except asyncio.CancelledError:
        # Stopped from outside (Ctrl-C, the app shutting down): the browser
        # closed on the way out, so the bot has left the call.
        await _move(meeting_id, MeetingStatus.LEFT, NOT_DONE)
        raise
    except Exception as exc:
        logger.exception("Meeting bot failed", meeting_id=meeting_id)
        await _move(meeting_id, MeetingStatus.FAILED, NOT_DONE, str(exc))


def start_meeting(meeting_id: int) -> asyncio.Task[None]:
    """Run the bot without waiting for it, in this process."""
    return background(run_meeting(meeting_id))
