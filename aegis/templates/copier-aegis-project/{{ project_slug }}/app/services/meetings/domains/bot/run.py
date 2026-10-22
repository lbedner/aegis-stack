"""The meeting bot's run: ask to join, wait to be admitted, say who it is,
stay until there is a reason to leave, and write each step on the meeting
row.

It runs inside whichever process starts it: the CLI waits for it
(``meetings join``), and the app hands it to the worker, or runs it in its
own process where the stack has none (``domains.bot.dispatch``). Stopped
at shutdown, it records itself as left. It writes the
row only through the service's ``transition`` and ``heartbeat``. Each step
opens its own short session, so an hour-long call holds no database
connection. What it hears goes to whoever the captions say was talking
(``audio.Hearing``).
"""

import asyncio
import math
from pathlib import Path

from app.core.config import settings
from app.core.db import get_async_session
from app.core.log import logger
from app.services.meetings.domains.accounts.service import login_secret_of, pick
from app.services.meetings.domains.bot.audio import Hearing
from app.services.meetings.domains.bot.dispatch import start_meeting
from app.services.meetings.domains.bot.meet import (
    CallState,
    MeetPage,
    merge_caption,
    open_meet,
)
from app.services.meetings.domains.bot.row import (
    heartbeat,
    transition,
    write_captions,
)
from app.services.meetings.domains.moments.tidy import cleaner
from app.services.meetings.domains.people.participants import keep_heard
from app.services.meetings.domains.people.service import guides_writer
from app.services.meetings.domains.series.service import themes_writer
from app.services.meetings.models import (
    NOT_DONE,
    STILL_WANTED,
    BotAccount,
    Caption,
    Meeting,
    MeetingStatus,
)
from app.services.meetings.service import JOINS, MeetingsService, notes_writer

POLL_SECONDS = 2.0
# Said in every call the bot joins, after who it is: nobody is recorded
# without being told.
TRANSCRIBED = "What is said here is transcribed."
ADMIT_TIMEOUT_SECONDS = 300.0
# How long the bot stays once everyone else has gone.
ALONE_SECONDS = 120.0
# How long it waits in a call nobody else has come to yet: the calendar
# sends it a minute early, and people come late.
WAIT_FOR_OTHERS_SECONDS = 900.0
# How long Leave can be gone before the bot takes the call as over: what
# Meet puts over the call (someone joining, a prompt) can hide it for a
# look. A page that says the call ended, or the bot was removed, is over
# at once.
GONE_SECONDS = 10.0
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
        self.text: dict[str, str] = {}  # caption line -> all of it heard so far
        # caption line -> when it was first captioned, from when the bot got in
        self.first_seen: dict[str, float] = {}
        self.pending: dict[str, Caption] = {}
        # When each speaker's caption last moved: who was talking when.
        self.spoke: list[tuple[float, str]] = []

    async def take(self, captions: list[Caption]) -> None:
        now = asyncio.get_running_loop().time()
        for c in captions:
            if self.seen.get(c.line) != c.text:
                self.seen[c.line] = c.text
                self.text[c.line] = merge_caption(self.text.get(c.line, ""), c.text)
                self.first_seen.setdefault(c.line, now - self.started)
                self.pending[c.line] = Caption(c.line, c.speaker, self.text[c.line])
                self.spoke.append((now, c.speaker))
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
                starts=self.first_seen,
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


async def _stay(
    call: MeetPage, pulse: _Pulse, transcript: _Transcript, hearing: Hearing
) -> None:
    """Back when the bot should leave: asked to, alone too long once the
    others have gone (nobody counted by Meet, nobody talking), or nobody
    came. Ends the run when the call ends on its own (any page but the
    call's). Each look keeps what was said since the last, and gives what
    was heard to its speaker once the captions have caught up."""
    loop = asyncio.get_running_loop()
    # Alone since the others went, or since the bot came while nobody had.
    alone_since: float | None = loop.time()
    others_came = False
    gone_since: float | None = None
    try:
        while True:
            state = await call.state()
            if state != CallState.IN_CALL:
                gone_since = loop.time() if gone_since is None else gone_since
                # Only Leave missing (WAITING) waits out GONE_SECONDS.
                gone = loop.time() - gone_since >= GONE_SECONDS
                if state != CallState.WAITING or gone:
                    await _left_because(call, transcript.meeting_id, state)
                    raise _RunEnded(MeetingStatus.LEFT)
                await asyncio.sleep(POLL_SECONDS)
                continue
            gone_since = None
            spoke = len(transcript.spoke)
            await transcript.take(await call.captions())
            hearing.settle(transcript.spoke, loop.time())
            if not await pulse.still_wanted():
                return
            # A caption that moved is someone here, whatever Meet's People
            # count says: it can read 1 with others in the call.
            talking = len(transcript.spoke) > spoke
            people = await call.people()
            if talking or people is None or people > 1:
                others_came = others_came or talking or people is not None
                alone_since = None
            elif alone_since is None:
                alone_since = loop.time()
            elif loop.time() - alone_since >= (
                ALONE_SECONDS if others_came else WAIT_FOR_OTHERS_SECONDS
            ):
                logger.info(
                    "Leaving: alone in the call",
                    meeting_id=transcript.meeting_id,
                    others_came=others_came,
                )
                return
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await transcript.flush()
        hearing.settle(transcript.spoke, math.inf)
        hearing.close()
        if hearing.seconds:
            async with get_async_session() as session:
                await keep_heard(session, transcript.meeting_id, hearing.seconds)


async def _left_because(call: MeetPage, meeting_id: int, state: CallState) -> None:
    """Say why the call is over for the bot, with what the page showed: the
    one record of a call it left on its own."""
    logger.warning(
        "The call is over for the bot",
        meeting_id=meeting_id,
        state=state,
        page=await call.page_text(),
    )


def announcement(name: str) -> str:
    """What the bot says when it joins: who it is
    (``MEETINGS_ANNOUNCEMENT``, ``{name}`` the name it joins as), then
    that the call is transcribed, whatever the first is set to."""
    who = settings.MEETINGS_ANNOUNCEMENT.replace("{name}", name).rstrip(" .:")
    return f"{who}. {TRANSCRIBED}"


async def _join(meeting: Meeting, login: str) -> None:
    """Into the call signed in as the agent it was sent as (``login``)."""
    meeting_id: int = meeting.id  # type: ignore[assignment]
    pulse = _Pulse(meeting_id)
    keep_in = settings.MEETINGS_KEEP_AUDIO_DIR
    hearing = Hearing(Path(keep_in) / str(meeting_id) if keep_in else None)
    async with open_meet(meeting.url, hearing.heard, login=login) as call:
        if not await pulse.still_wanted():
            raise _RunEnded(MeetingStatus.LEFT)
        await call.ask_to_join(meeting.bot_name)
        await _step(meeting_id, MeetingStatus.WAITING, MeetingStatus.JOINING)
        await _admitted(call, pulse)
        await _step(meeting_id, MeetingStatus.IN_CALL, MeetingStatus.WAITING)
        transcript = _Transcript(meeting_id)
        await call.say(announcement(meeting.bot_name))
        if not await call.turn_on_captions():
            logger.warning("No captions in this call", meeting_id=meeting_id)
        await _stay(call, pulse, transcript, hearing)
        await call.leave()


async def _after(meeting_id: int) -> None:
    """Once the bot is out: the notes, the questions cleaned up, how to work
    with each person and what the meeting's series keeps coming back to,
    where the stack has a model to write them."""
    if (write := notes_writer()) is not None:
        await write(meeting_id)
    if (clean := cleaner()) is not None:
        await clean(meeting_id)
    if (guide := guides_writer()) is not None:
        await guide(meeting_id)
    if (themes := themes_writer()) is not None:
        await themes(meeting_id)


async def run_meeting(meeting_id: int) -> None:
    """Take the bot through one meeting, start to finish, then write what
    it came to. Stopped from outside, it writes nothing (the page can). A
    meeting already taken (by another run, or left before any) is not this
    run's: a job delivered twice does nothing the second time."""
    if not await _move(meeting_id, MeetingStatus.JOINING, (MeetingStatus.REQUESTED,)):
        return
    async with get_async_session() as session:
        meeting = await MeetingsService(session, None).get(meeting_id)
        login = await login_secret_of(session, meeting.account_id)
    try:
        if meeting.platform not in JOINS:
            raise _RunEnded(
                MeetingStatus.FAILED,
                f"The bot joins Google Meet so far, not {meeting.platform.title()}",
            )
        await _join(meeting, login)
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
    await _after(meeting_id)


async def send_bot(
    svc: MeetingsService,
    url: str,
    bot_name: str,
    agent: str | None = None,
    every: list[BotAccount] | None = None,
) -> Meeting:
    """Record the meeting and start the bot on it as ``agent`` (the default
    when none is named; of ``every``, the agents, when read already),
    without waiting: the one way in for the Meetings page, Overseer and the
    API. It joins as the agent's name unless given ``bot_name``."""
    account = await pick(svc.db, agent, every)
    meeting = await svc.request(
        url, bot_name.strip() or account.display_name, account.id
    )
    meeting_id: int = meeting.id  # type: ignore[assignment]
    try:
        await start_meeting(meeting_id)
    except Exception as exc:
        # Nothing will ever run it: say so on the row, not only in this log.
        logger.exception("Meeting bot not started", meeting_id=meeting_id)
        await transition(
            svc.db,
            meeting_id,
            MeetingStatus.FAILED,
            from_=(MeetingStatus.REQUESTED,),
            reason=f"The bot could not be started: {exc}",
        )
    return meeting
