"""Meetings, read and requested for one owner (``owner_user_id``; ``None``
on a project without auth reads every meeting)."""

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import importlib
from importlib.util import find_spec
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, func, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.formatting import format_clock, format_span
from app.core.time import utcnow
from app.services.meetings.models import (
    Caption,
    Meeting,
    MeetingNotes,
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

    async def request(self, url: str, bot_name: str = DEFAULT_BOT_NAME) -> Meeting:
        """Record a meeting for the bot to join; a link it cannot join raises
        ``UnsupportedMeetingLinkError`` before anything is stored."""
        url = url.strip()
        meeting = Meeting(
            owner_user_id=self.owner_user_id,
            url=url,
            platform=detect_platform(url),
            bot_name=bot_name,
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
        """Ask the bot to leave; it goes on its next look, or never joins.
        A meeting it is done with is left as it is."""
        meeting = await self.get(meeting_id)
        await transition(
            self.db,
            meeting_id,
            MeetingStatus.LEAVING,
            from_=LEAVABLE,
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
        return MeetingRecord(
            meeting=meeting,
            notes=kept.notes() if kept else None,
            notes_error=kept.error if kept else None,
            model_name=kept.model_name if kept else None,
            transcript=transcript,
            status=status_label(meeting.status),
            length=call_length(meeting.joined_at, meeting.left_at),
            heard=heard_line(meeting.heard),
            can_leave=meeting.status in LEAVABLE,
            can_delete=meeting.status not in IN_PROGRESS,
        )

    async def transcript(self, meeting: Meeting) -> list[tuple[str, TranscriptLine]]:
        """Each line of ``meeting`` (one ``get`` returned) with its speaker's
        name, in the order it was said."""
        query = (
            select(MeetingParticipant.display_name, TranscriptLine)
            .join(
                MeetingParticipant,
                col(TranscriptLine.participant_id) == MeetingParticipant.id,
                isouter=True,
            )
            .where(TranscriptLine.meeting_id == meeting.id)
            # Lines captioned in the same look keep the order Meet showed them.
            .order_by(col(TranscriptLine.start_seconds), col(TranscriptLine.id))
        )
        return [(name or "Unknown", line) for name, line in await self.db.exec(query)]

    async def set_me(self, meeting_id: int, name: str | None) -> Meeting:
        """Say which speaker the owner is (None: none of them)."""
        meeting = await self.get(meeting_id)
        if name is not None and name not in await speakers(self.db, meeting_id):
            raise NotASpeakerError(f"Nobody called {name} spoke in this meeting")
        meeting.me = name
        self.db.add(meeting)
        await self.db.commit()
        return meeting

    async def delete(self, meeting_id: int) -> None:
        """The meeting and everything kept of it: notes, transcript and
        participants. One the bot is still in is refused: ask it to leave
        first."""
        meeting = await self.get(meeting_id)
        if meeting.status in IN_PROGRESS:
            raise MeetingInProgressError(
                "The bot is still in this meeting: ask it to leave first"
            )
        for kept in (MeetingNotes, TranscriptLine, MeetingParticipant):
            await self.db.exec(delete(kept).where(col(kept.meeting_id) == meeting_id))  # type: ignore[call-overload]
        await self.db.delete(meeting)
        await self.db.commit()

    async def notes_for(self, meeting_ids: list[int]) -> dict[int, MeetingNotes]:
        """The notes of meetings this owner was given (``get``,
        ``list_meetings``), by meeting id."""
        if not meeting_ids:
            return {}
        query = select(MeetingNotes).where(
            col(MeetingNotes.meeting_id).in_(meeting_ids)
        )
        return {n.meeting_id: n for n in (await self.db.exec(query)).all()}


def notes_writer() -> Callable[[int], Awaitable[None]] | None:
    """What writes a meeting's notes, where the stack has a model to."""
    if find_spec(NOTES) is None:
        return None
    return importlib.import_module(NOTES).write_notes


async def speakers(db: AsyncSession, meeting_id: int) -> list[str]:
    """Everyone who spoke in the meeting, by name."""
    query = (
        select(MeetingParticipant.display_name)
        .where(MeetingParticipant.meeting_id == meeting_id)
        .order_by(col(MeetingParticipant.display_name))
    )
    return list((await db.exec(query)).all())


async def remember_me(db: AsyncSession, meeting_id: int) -> None:
    """Until the owner says, they are the speaker they were in their last
    meeting that says, when someone by that name spoke in this one."""
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None or meeting.me is not None:
        return
    query = (
        select(Meeting.me)
        .where(
            *owner_filters(Meeting.owner_user_id, meeting.owner_user_id),
            col(Meeting.me).is_not(None),
            Meeting.id != meeting_id,
        )
        .order_by(col(Meeting.created_at).desc(), col(Meeting.id).desc())
        .limit(1)
    )
    last = (await db.exec(query)).first()
    if last is not None and last in await speakers(db, meeting_id):
        meeting.me = last
        db.add(meeting)
        await db.commit()


async def save_notes(db: AsyncSession, notes: MeetingNotes) -> None:
    """Keep a meeting's notes, over any it had."""
    await db.merge(notes)
    await db.commit()


async def save_heard(
    db: AsyncSession, meeting_id: int, heard: dict[str, float]
) -> None:
    """Keep how many seconds of each speaker the bot heard."""
    await db.exec(  # type: ignore[call-overload]
        update(Meeting).where(col(Meeting.id) == meeting_id).values(heard=heard)
    )
    await db.commit()


def status_label(status: str) -> str:
    """A meeting's status as the pages say it: "in_call" -> "In call"."""
    return status.replace("_", " ").capitalize()


def call_length(joined: datetime | None, left: datetime | None) -> str | None:
    """How long the bot was in the call, as a stopwatch reads it; None
    until it has been in and out."""
    if joined is None or left is None:
        return None
    return format_clock((left - joined).total_seconds())


def heard_line(heard: dict[str, float] | None) -> str | None:
    """How long each speaker was heard, most heard first: "Ada 4m 10s ·
    Leonard 2m 30s"; None when nobody was."""
    if not heard:
        return None
    ranked = sorted(heard.items(), key=lambda item: -item[1])
    return " · ".join(f"{name} {format_span(seconds)}" for name, seconds in ranked)


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
    speakers = await _participants(db, meeting_id, {c.speaker for c in new})
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


async def _participants(
    db: AsyncSession, meeting_id: int, names: set[str]
) -> dict[str, int]:
    """The meeting's participant id for each display name, adding those it
    does not have yet."""
    if not names:
        return {}
    found = await db.exec(
        select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            col(MeetingParticipant.display_name).in_(names),
        )
    )
    known = {p.display_name: p for p in found.all()}
    fresh = [
        MeetingParticipant(meeting_id=meeting_id, display_name=name)
        for name in names - known.keys()
    ]
    db.add_all(fresh)
    await db.flush()
    return {p.display_name: p.id for p in [*known.values(), *fresh]}
