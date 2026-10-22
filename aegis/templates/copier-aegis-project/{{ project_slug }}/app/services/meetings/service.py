"""Meetings, read and requested for one owner (``owner_user_id``; ``None``
on a project without auth reads every meeting)."""

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
import zlib

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.concurrency import background
from app.core.constants import CHART_RAMP
from app.core.discovery import optional
from app.core.formatting import format_clock, format_span
from app.services.meetings import queries
from app.services.meetings.domains.bot.row import transition
from app.services.meetings.domains.moments import service as moments
from app.services.meetings.domains.moments import tidy
from app.services.meetings.domains.notes import queries as notes_queries
from app.services.meetings.domains.notes.service import notes_of
from app.services.meetings.domains.people import participants
from app.services.meetings.domains.people import queries as people_queries
from app.services.meetings.domains.series import queries as series_queries
from app.services.meetings.models import (
    IN_PROGRESS,
    LEAVABLE,
    NOT_DONE,
    STILL_WANTED,
    UNKNOWN,
    KeptNotes,
    Meeting,
    MeetingActionRun,
    MeetingGuidePoint,
    MeetingGuidePointLine,
    MeetingNoteItem,
    MeetingNoteLine,
    MeetingRecord,
    MeetingStatus,
    MeetingTheme,
    MeetingThemeLine,
    Platform,
    TranscriptLine,
    TranscriptRow,
)
from app.services.shared import facade

if TYPE_CHECKING:
    # What callers outside reach through here, each loaded when used
    # (``app.services.shared.facade``); the agents' seeds render only
    # with an AI that runs them.
    from app.services.meetings.domains.actions.runs import (  # noqa: F401
        fail_abandoned,
    )
    from app.services.meetings.domains.agents import (  # noqa: F401
        load_meetings_agent_fixtures,
    )
    from app.services.meetings.domains.bot.row import (  # noqa: F401
        STALE_SECONDS,
        fail_interrupted,
        heartbeat,
        write_captions,
    )
    from app.services.meetings.domains.bot.run import (  # noqa: F401
        run_meeting,
        send_bot,
    )
    from app.services.meetings.domains.moments.service import (  # noqa: F401
        by_kind,
    )

DEFAULT_BOT_NAME = "Notetaker"

# The model pass that writes a meeting's notes: only a stack with a model
# to ask (ai on pydantic-ai, with a database) has the module.
NOTES = "app.services.meetings.domains.notes.writer"
# The meetings whose notes this process is writing now.
WRITING: set[int] = set()


class UnsupportedMeetingLinkError(ValueError):
    """A link the bot cannot join."""


class MeetingNotFoundError(LookupError):
    """No such meeting for this owner."""


class MeetingInProgressError(RuntimeError):
    """The bot is still in the meeting."""


class NotASpeakerError(ValueError):
    """Nobody by that name spoke in the meeting."""


class NothingToWriteError(RuntimeError):
    """The notes cannot be written now: no model to, the bot is still in,
    nothing was said, or a writer is already at it."""


# The platforms the bot joins so far; it recognizes the others' links.
JOINS = frozenset({Platform.MEET})


def can_join(url: str) -> bool:
    """Whether the bot can join the meeting at ``url`` now."""
    try:
        return detect_platform(url) in JOINS
    except UnsupportedMeetingLinkError:
        return False


def detect_platform(url: str) -> Platform:
    """The platform a meeting link belongs to; any other link is refused."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path.strip("/")
    if parts.scheme == "https" and path:
        if host == "meet.google.com":
            return Platform.MEET
        if host in ("teams.microsoft.com", "teams.live.com"):
            return Platform.TEAMS
        if (host == "zoom.us" or host.endswith(".zoom.us")) and path.startswith(
            ("j/", "wc/")
        ):
            return Platform.ZOOM
    raise UnsupportedMeetingLinkError(
        f"Not a meeting link the bot can join: {url}. "
        "It joins Google Meet, Microsoft Teams or Zoom links."
    )


class MeetingsService:
    def __init__(self, db: AsyncSession, owner_user_id: int | None) -> None:
        self.db = db
        self.owner_user_id = owner_user_id

    async def request(
        self, url: str, bot_name: str = DEFAULT_BOT_NAME, account_id: int | None = None
    ) -> Meeting:
        """Record a meeting for the bot to join as ``account_id`` (an agent),
        called what its calendar calls it; a link it cannot join raises
        ``UnsupportedMeetingLinkError`` before anything is stored."""
        url = url.strip()
        meeting = Meeting(
            owner_user_id=self.owner_user_id,
            url=url,
            title=await queries.title_for(self.db, url),
            platform=detect_platform(url),
            bot_name=bot_name,
            account_id=account_id,
        )
        self.db.add(meeting)
        await self.db.commit()
        return meeting

    async def list_meetings(self, limit: int = 50) -> list[Meeting]:
        """Newest first."""
        return await queries.meetings_of(self.db, self.owner_user_id, limit)

    async def get(self, meeting_id: int) -> Meeting:
        meeting = await queries.meeting(self.db, meeting_id, self.owner_user_id)
        if meeting is None:
            raise MeetingNotFoundError(f"No meeting {meeting_id}")
        return meeting

    async def ask_to_leave(self, meeting_id: int) -> Meeting:
        """Ask the bot to leave; it goes on its next look. One no run has
        taken yet is left at once, so a run that comes for it later finds it
        taken. A meeting it is done with is left as it is."""
        meeting = await self.get(meeting_id)
        if not await transition(
            self.db, meeting_id, MeetingStatus.LEFT, from_=(MeetingStatus.REQUESTED,)
        ):
            await transition(
                self.db, meeting_id, MeetingStatus.LEAVING, from_=STILL_WANTED
            )
        return meeting

    async def read(self, meeting_id: int) -> MeetingRecord:
        """The meeting in full: its notes (or why there are none), its
        transcript, and what the pages say of it."""
        meeting = await self.get(meeting_id)
        kept = (await self.notes_for([meeting_id])).get(meeting_id)
        lines = await self.transcript(meeting)
        transcript = [
            TranscriptRow(
                id=line.id,  # type: ignore[arg-type]
                speaker=speaker,
                at=line.start_seconds,
                text=line.text,
            )
            for speaker, line in lines
        ]
        notes = kept.notes if kept else None
        here = await people_queries.meeting_people(self.db, meeting_id)
        heard = participants.heard_in(here, meeting)
        mine = (
            notes.mine(await people_queries.my_names(self.db, meeting.owner_user_id))
            if notes
            else []
        )
        under_way = meeting.status in NOT_DONE
        writing = meeting_id in WRITING
        cleaning = meeting_id in tidy.CLEANING
        can_write = notes_writer() is not None
        finished = bool(transcript) and not under_way
        found = await moments.moments_of(
            self.db, meeting_id, [(row.speaker, row.id, row.text) for row in transcript]
        )
        return MeetingRecord(
            meeting=meeting,
            moments=found,
            following=under_way or writing or cleaning or moments.answering(found),
            notes=notes,
            notes_error=kept.error if kept else None,
            model_name=kept.model_name if kept else None,
            transcript=transcript,
            status=status_label(meeting.status),
            length=call_length(meeting.joined_at, meeting.left_at),
            heard=heard_line(heard),
            heard_seconds=heard,
            # Only a speaker has a participant row: the transcript names them.
            people=sorted({row.speaker for row in transcript}),
            me=participants.me_in(here),
            mine=mine,
            under_way=under_way,
            writing=writing,
            can_leave=meeting.status in LEAVABLE,
            can_delete=meeting.status not in IN_PROGRESS,
            can_write=can_write,
            can_rewrite=can_write and finished and not writing,
            can_look_over=finished,
        )

    async def write_notes_again(self, meeting_id: int) -> MeetingRecord:
        """Start writing the notes over the old ones, in the background; the
        read it returns says they are being written."""
        record = await self.read(meeting_id)
        write = notes_writer()
        if write is None or not record.can_rewrite:
            raise NothingToWriteError("No notes to write now")
        WRITING.add(meeting_id)
        background(write(meeting_id))
        return record.model_copy(
            update={"writing": True, "following": True, "can_rewrite": False}
        )

    async def look_over(self, meeting_id: int) -> MeetingRecord:
        """Read the call over again; the read it returns follows its clean-up."""
        await self.get(meeting_id)
        await tidy.look_over(self.db, [meeting_id], wait=False)
        return await self.read(meeting_id)

    async def ask(self, meeting_id: int, moment_id: int, name: str) -> MeetingActionRun:
        """Ask the action ``name`` of a moment in one of the owner's meetings
        (of its burst): in the app it starts at once; on a runner it waits."""
        return await moments.ask(
            self.db, meeting_id, moment_id, name, self.owner_user_id
        )

    async def transcript(self, meeting: Meeting) -> list[tuple[str, TranscriptLine]]:
        """Each line of ``meeting`` (one ``get`` returned) with its speaker's
        name, in the order it was said."""
        lines = await queries.transcript(self.db, meeting.id)
        return [(name or UNKNOWN, line) for name, line in lines]

    async def set_me(self, meeting_id: int, name: str | None) -> Meeting:
        """Say which speaker the owner is (None: none of them): that
        person is the owner in every meeting they are in."""
        meeting = await self.get(meeting_id)
        if not await participants.set_me(self.db, meeting_id, name):
            raise NotASpeakerError(f"Nobody called {name} spoke in this meeting")
        await self.db.commit()
        return meeting

    async def delete(self, meeting_id: int) -> None:
        """The meeting and everything kept of it (its notes, transcript and
        participants go with it), anyone who spoke only in it (and their
        guide), whatever elsewhere cited only its lines (another meeting's
        note item, a guide's point, a series' theme, a contradiction left
        with one side), and its series if it was the last on its link. One
        the bot is still in is refused: ask it to leave first."""
        meeting = await self.get(meeting_id)
        if meeting.status in IN_PROGRESS:
            raise MeetingInProgressError(
                "The bot is still in this meeting: ask it to leave first"
            )
        items = await notes_queries.citing(self.db, MeetingNoteLine.item_id, meeting_id)
        points = await notes_queries.citing(
            self.db, MeetingGuidePointLine.point_id, meeting_id
        )
        themes = await notes_queries.citing(
            self.db, MeetingThemeLine.theme_id, meeting_id
        )
        here = await people_queries.meeting_people(self.db, meeting_id)
        owner, link = meeting.owner_user_id, series_queries.series_link(meeting.url)
        await self.db.delete(meeting)
        await self.db.flush()
        await notes_queries.delete_in(
            self.db,
            MeetingNoteItem.id,
            await notes_queries.left_uncited(self.db, items),
        )
        await notes_queries.delete_in(
            self.db,
            MeetingGuidePoint.id,
            await notes_queries.citing_nothing(
                self.db, MeetingGuidePointLine.point_id, points
            ),
        )
        await notes_queries.delete_in(
            self.db,
            MeetingTheme.id,
            await notes_queries.citing_nothing(
                self.db, MeetingThemeLine.theme_id, themes
            ),
        )
        await series_queries.drop_if_empty(self.db, owner, link)
        await people_queries.drop_people_in_no_meeting(
            self.db,
            [person.id for _, person in here],  # type: ignore[misc]
        )
        await self.db.commit()

    async def mine_counts(self, meeting_ids: list[int]) -> dict[int, int]:
        """How many action items the owner has to do in each of those
        meetings' notes, by meeting id: only meetings with notes."""
        names = await people_queries.my_names(self.db, self.owner_user_id)
        return await notes_queries.mine_counts(self.db, meeting_ids, names)

    async def notes_for(self, meeting_ids: list[int]) -> dict[int, KeptNotes]:
        """The notes of meetings this owner was given (``get``,
        ``list_meetings``), by meeting id."""
        return await notes_of(self.db, meeting_ids)


def notes_writer() -> Callable[[int], Awaitable[None]] | None:
    """What writes a meeting's notes, where the stack has a model to."""
    return optional(NOTES, "write_notes")


def voice(name: str) -> int:
    """The theme's color a speaker's name points at, 1 to ``CHART_RAMP``: the
    same in every meeting, unless someone in it already has it
    (``voices``)."""
    return zlib.crc32(name.encode()) % CHART_RAMP + 1


def voices(names: Iterable[str]) -> dict[str, int]:
    """A color for each speaker in one meeting, none shared while the
    colors last: each keeps their name's (``voice``) unless someone already
    has it, then takes the next free one."""
    taken: dict[str, int] = {}
    for name in sorted(set(names)):
        color = voice(name)
        while color in taken.values() and len(taken) < CHART_RAMP:
            color = color % CHART_RAMP + 1
        taken[name] = color
    return taken


def status_label(status: str) -> str:
    """A meeting's status as the pages say it: "in_call" -> "In call"."""
    return status.replace("_", " ").capitalize()


def call_length(joined: datetime | None, left: datetime | None) -> str | None:
    """How long the bot was in the call, as a stopwatch reads it; None
    until it has been in and out."""
    if joined is None or left is None:
        return None
    return format_clock((left - joined).total_seconds())


def heard_rows(heard: dict[str, float]) -> list[tuple[str, str, float]]:
    """How long each speaker was heard, most heard first: their name, the
    time ("4m 10s") and how it compares with the most heard (1.0)."""
    most = max(heard.values(), default=0) or 1
    ranked = sorted(heard.items(), key=lambda item: -item[1])
    return [
        (name, format_span(seconds) or "0s", seconds / most) for name, seconds in ranked
    ]


def heard_line(heard: dict[str, float]) -> str | None:
    """``heard_rows`` on one line: "Ada 4m 10s · Leonard 2m 30s"; None when
    nobody was heard."""
    rows = heard_rows(heard)
    return " · ".join(f"{name} {span}" for name, span, _ in rows) or None


async def meetings_counts(db: AsyncSession) -> dict[str, Any]:
    """Across every owner, for the health check."""
    meetings, in_call = await queries.counts(db)
    return {"meetings": meetings, "in_call": in_call}


__getattr__ = facade.lazy(__name__, __file__)[0]
