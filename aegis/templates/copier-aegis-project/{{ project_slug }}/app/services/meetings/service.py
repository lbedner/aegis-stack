"""Meetings, read and requested for one owner (``owner_user_id``; ``None``
on a project without auth reads every meeting)."""

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timedelta
import importlib
from importlib.util import find_spec
from typing import Any
from urllib.parse import urlsplit
import zlib

from sqlalchemy import func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.concurrency import background
from app.core.constants import CHART_RAMP
from app.core.formatting import format_clock, format_span
from app.core.time import utcnow
from app.services.meetings.domains.notes import queries as notes_queries
from app.services.meetings.domains.notes.service import notes_of
from app.services.meetings.domains.people import participants
from app.services.meetings.domains.people import queries as people_queries
from app.services.meetings.models import (
    UNKNOWN,
    Caption,
    KeptNotes,
    Meeting,
    MeetingGuidePoint,
    MeetingGuidePointLine,
    MeetingNoteItem,
    MeetingNoteLine,
    MeetingParticipant,
    MeetingRecord,
    MeetingStatus,
    Platform,
    TranscriptLine,
    TranscriptRow,
)
from app.services.shared.queries import owner_filters

DEFAULT_BOT_NAME = "Notetaker"


# A meeting the bot is on its way into or in, and not asked to leave.
STILL_WANTED = (MeetingStatus.JOINING, MeetingStatus.WAITING, MeetingStatus.IN_CALL)
# Those, and one it is on its way out of: its run beats (``seen_at``) meanwhile.
IN_PROGRESS = (*STILL_WANTED, MeetingStatus.LEAVING)
NOT_DONE = (MeetingStatus.REQUESTED, *IN_PROGRESS)
# One the bot can still be asked to leave (``ask_to_leave``).
LEAVABLE = (MeetingStatus.REQUESTED, *STILL_WANTED)
# A run whose heartbeat is older than this is gone (the process stopped).
STALE_SECONDS = 60
# The model pass that writes a meeting's notes: only a stack with a model
# to ask (ai on pydantic-ai, with a database) has the module.
NOTES = "app.services.meetings.notes"
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
        """Record a meeting for the bot to join as ``account_id`` (an agent);
        a link it cannot join raises ``UnsupportedMeetingLinkError`` before
        anything is stored."""
        url = url.strip()
        meeting = Meeting(
            owner_user_id=self.owner_user_id,
            url=url,
            platform=detect_platform(url),
            bot_name=bot_name,
            account_id=account_id,
        )
        self.db.add(meeting)
        await self.db.commit()
        return meeting

    async def list_meetings(self, limit: int = 50) -> list[Meeting]:
        """Newest first."""
        query = (
            select(Meeting)
            .where(*owner_filters(Meeting.owner_user_id, self.owner_user_id))
            .order_by(col(Meeting.created_at).desc(), col(Meeting.id).desc())
            .limit(limit)
        )
        return list((await self.db.exec(query)).all())

    async def get(self, meeting_id: int) -> Meeting:
        query = select(Meeting).where(
            Meeting.id == meeting_id,
            *owner_filters(Meeting.owner_user_id, self.owner_user_id),
        )
        meeting = (await self.db.exec(query)).first()
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
        transcript = [
            TranscriptRow(
                id=line.id,  # type: ignore[arg-type]
                speaker=speaker,
                at=line.start_seconds,
                text=line.text,
            )
            for speaker, line in await self.transcript(meeting)
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
        can_write = notes_writer() is not None
        return MeetingRecord(
            meeting=meeting,
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
            can_rewrite=(
                can_write and bool(transcript) and not under_way and not writing
            ),
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
        return record.model_copy(update={"writing": True, "can_rewrite": False})

    async def transcript(self, meeting: Meeting) -> list[tuple[str, TranscriptLine]]:
        """Each line of ``meeting`` (one ``get`` returned) with its speaker's
        name, in the order it was said."""
        query = (
            notes_queries.with_speaker(
                select(MeetingParticipant.display_name, TranscriptLine)
            )
            .where(TranscriptLine.meeting_id == meeting.id)
            # Lines captioned in the same look keep the order Meet showed them.
            .order_by(col(TranscriptLine.start_seconds), col(TranscriptLine.id))
        )
        return [(name or UNKNOWN, line) for name, line in await self.db.exec(query)]

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
        guide), and whatever elsewhere cited only its lines: another
        meeting's note item, a guide's point, a contradiction left with
        one side. One the bot is still in is
        refused: ask it to leave first."""
        meeting = await self.get(meeting_id)
        if meeting.status in IN_PROGRESS:
            raise MeetingInProgressError(
                "The bot is still in this meeting: ask it to leave first"
            )
        items = await notes_queries.citing(self.db, MeetingNoteLine.item_id, meeting_id)
        points = await notes_queries.citing(
            self.db, MeetingGuidePointLine.point_id, meeting_id
        )
        here = await people_queries.meeting_people(self.db, meeting_id)
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
            await people_queries.points_left_uncited(self.db, points),
        )
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
    if find_spec(NOTES) is None:
        return None
    return importlib.import_module(NOTES).write_notes


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
    meetings, in_call = (
        await db.exec(
            select(
                func.count(),
                func.count().filter(col(Meeting.status) == MeetingStatus.IN_CALL),
            ).select_from(Meeting)
        )
    ).one()
    return {"meetings": meetings, "in_call": in_call}


async def transition(
    db: AsyncSession,
    meeting_id: int,
    to: MeetingStatus,
    *,
    from_: tuple[MeetingStatus, ...],
    reason: str | None = None,
) -> bool:
    """Move a meeting to ``to`` only from one of ``from_``, in one statement,
    and say whether it moved. Every status change goes through here, so a
    leave request or a failure written by one process is never overwritten
    by a run in another. A move is a heartbeat too (``seen_at``): a run's
    slow browser steps each sit between two moves or beats."""
    now = utcnow()
    values: dict[str, Any] = {"status": to, "seen_at": now}
    if to == MeetingStatus.IN_CALL:
        values["joined_at"] = now
    if to == MeetingStatus.LEFT:
        values["left_at"] = now
    if to == MeetingStatus.FAILED:
        values["failure_reason"] = reason
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(col(Meeting.id) == meeting_id, col(Meeting.status).in_(from_))
        .values(**values)
    )
    await db.commit()
    return result.rowcount == 1


async def heartbeat(db: AsyncSession, meeting_id: int) -> str | None:
    """A run's pulse: stamp ``seen_at`` and read the status back, in one
    statement. The status is how a leave request reaches the run."""
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(col(Meeting.id) == meeting_id)
        .values(seen_at=utcnow())
        .returning(col(Meeting.status))
    )
    status = result.scalar_one_or_none()
    await db.commit()
    return status


async def fail_interrupted(db: AsyncSession) -> int:
    """A meeting whose run stopped beating (its process stopped) is over,
    and says why. A run another process is still in keeps beating, so it is
    left alone. Returns how many there were."""
    stale = utcnow() - timedelta(seconds=STALE_SECONDS)
    result = await db.exec(  # type: ignore[call-overload]
        update(Meeting)
        .where(
            col(Meeting.status).in_(IN_PROGRESS),
            or_(col(Meeting.seen_at).is_(None), col(Meeting.seen_at) < stale),
        )
        .values(
            status=MeetingStatus.FAILED,
            failure_reason="The app stopped during the meeting",
        )
    )
    await db.commit()
    return result.rowcount


async def write_captions(
    db: AsyncSession,
    meeting_id: int,
    captions: list[Caption],
    rows: dict[str, int],
    at_seconds: float,
    starts: dict[str, float],
) -> None:
    """Each caption as its transcript line: a caption already in ``rows``
    (caption line -> row id) updates its row, a new one adds a row (and
    its id to ``rows``), its speaker becoming a participant the first time
    they speak. A new line starts when it was first captioned (``starts``,
    by caption line); ``at_seconds`` is when it last changed."""
    new = [c for c in captions if c.line not in rows]
    speakers = (
        await participants.participants(
            db, await db.get_one(Meeting, meeting_id), {c.speaker for c in new}
        )
        if new
        else {}
    )
    added = {
        c.line: TranscriptLine(
            meeting_id=meeting_id,
            participant_id=speakers[c.speaker],
            start_seconds=starts[c.line],
            end_seconds=at_seconds,
            text=c.text,
        )
        for c in new
    }
    db.add_all(added.values())
    changed = [
        {"id": rows[c.line], "text": c.text, "end_seconds": at_seconds}
        for c in captions
        if c.line in rows
    ]
    if changed:
        await db.exec(update(TranscriptLine), params=changed)
    await db.flush()
    rows |= {line: row.id for line, row in added.items()}
    await db.commit()
