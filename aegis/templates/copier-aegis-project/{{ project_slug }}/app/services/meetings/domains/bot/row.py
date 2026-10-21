"""The bot's run as kept on its meeting row: every status change, the
heartbeat that tells a live run from a stopped one, failing the runs that
stopped, and the captions as transcript lines. Each commits: a run holds
no session across a slow browser step."""

from datetime import timedelta
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.meetings import queries
from app.services.meetings.domains.actions import runs
from app.services.meetings.domains.moments import service as moments
from app.services.meetings.domains.people import participants
from app.services.meetings.models import (
    IN_PROGRESS,
    Caption,
    Meeting,
    MeetingStatus,
    TranscriptLine,
)

# A run whose heartbeat is older than this is gone (the process stopped).
STALE_SECONDS = 60


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
    moved = await queries.move(db, meeting_id, from_, values)
    await db.commit()
    return moved


async def heartbeat(db: AsyncSession, meeting_id: int) -> str | None:
    """A run's pulse: stamp ``seen_at`` and read the status back, in one
    statement. The status is how a leave request reaches the run."""
    status = await queries.beat(db, meeting_id, utcnow())
    await db.commit()
    return status


async def fail_interrupted(db: AsyncSession) -> int:
    """A meeting whose run stopped beating (its process stopped) is over,
    and says why. A run another process is still in keeps beating, so it is
    left alone. Returns how many there were."""
    stale = utcnow() - timedelta(seconds=STALE_SECONDS)
    failed = await queries.fail_stale(db, IN_PROGRESS, stale)
    await db.commit()
    return failed


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
        await queries.update_lines(db, changed)
    await db.flush()
    rows |= {line: row.id for line, row in added.items()}
    made = await moments.seen(db, meeting_id, {rows[c.line]: c.text for c in captions})
    await runs.ask_for_new(db, made)
    await db.commit()
