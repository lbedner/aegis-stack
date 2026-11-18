"""The reads behind actions: a moment as one owner may see it, and a
meeting's runs with the questions they answer. The runs themselves are
the runner component's (``app.components.runner``), about moments."""

from datetime import datetime
from typing import Any

from sqlalchemy import Select, String, cast, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.runner import runs
from app.components.runner.models import DONE, FAILED, GOING, RunnerRun
from app.services.meetings.domains.moments.detectors import ADDRESSED
from app.services.meetings.domains.notes.queries import with_speaker
from app.services.meetings.models import (
    MOMENT,
    UNKNOWN,
    Going,
    Meeting,
    MeetingMoment,
    MeetingParticipant,
    TranscriptLine,
    moment_of,
    subjects,
)
from app.services.shared.queries import owner_filters


def _owned(query: Any, owner_user_id: int | None) -> Any:
    """``query`` over moments (or what joins them), kept to the owner's
    meetings."""
    return query.join(Meeting, col(Meeting.id) == MeetingMoment.meeting_id).where(
        *owner_filters(Meeting.owner_user_id, owner_user_id)
    )


# A moment as the subject its runs are about, in a statement (``subjects``
# says the same of ids in hand).
_SUBJECT = cast(col(MeetingMoment.id), String)


async def moment(
    db: AsyncSession,
    moment_id: int,
    owner_user_id: int | None,
    meeting_id: int | None = None,
) -> tuple[MeetingMoment, int | None, str | None, datetime] | None:
    """The moment, and of its meeting whose it is, what its calendar calls
    it and when it was held (joined, else asked for), if it is in one of
    the owner's meetings (``meeting_id``, when given)."""
    held = func.coalesce(col(Meeting.joined_at), col(Meeting.created_at))
    found = select(MeetingMoment, Meeting.owner_user_id, Meeting.title, held)
    query = _owned(found, owner_user_id).where(
        col(MeetingMoment.id) == moment_id,
        *([MeetingMoment.meeting_id == meeting_id] if meeting_id else []),
    )
    return (await db.exec(query)).first()


def asked_in(meeting_id: int) -> Select[tuple[str]]:
    """What the meeting's runs are about: its moments, as subjects, read
    in the statement that takes them."""
    return select(_SUBJECT).where(MeetingMoment.meeting_id == meeting_id)


async def answered(
    db: AsyncSession, moment_ids: list[int], action: str
) -> dict[int, tuple[str, str | None]]:
    """These moments' runs of ``action`` that are over (done or failed):
    each one's status and result, by moment."""
    over = await runs.answered(db, MOMENT, subjects(moment_ids), action)
    return {int(subject): answer for subject, answer in over.items()}


async def going_in(db: AsyncSession, meeting_id: int) -> list[Going]:
    """The meeting's runs not yet done (asked, claimed), oldest first, each
    with the question it answers and who asked it."""
    query = _runs_in(meeting_id).where(col(RunnerRun.status).in_(GOING))
    order = (col(RunnerRun.asked_at), col(RunnerRun.id))
    return await _going(db, query.order_by(*order))


async def answered_in(db: AsyncSession, meeting_id: int, last: int = 3) -> list[Going]:
    """The meeting's last ``last`` answers to lines put to the bot by name
    (said aloud and posted in the call's chat), done or failed, newest
    first, each with what it came back with."""
    query = _runs_in(meeting_id).where(
        col(RunnerRun.status).in_((DONE, FAILED)),
        MeetingMoment.kind == ADDRESSED,
    )
    order = (col(RunnerRun.finished_at).desc(), col(RunnerRun.id).desc())
    return await _going(db, query.order_by(*order).limit(last))


def _runs_in(meeting_id: int) -> Any:
    """The meeting's runs, each with its question and who asked it."""
    about_a_moment = (RunnerRun.subject_kind == MOMENT) & (
        _SUBJECT == RunnerRun.subject_id
    )
    return with_speaker(
        select(RunnerRun, MeetingParticipant.display_name, MeetingMoment.text)
        .join(MeetingMoment, about_a_moment)
        .join(TranscriptLine, col(TranscriptLine.id) == MeetingMoment.line_id)
    ).where(MeetingMoment.meeting_id == meeting_id)


async def _going(db: AsyncSession, query: Any) -> list[Going]:
    return [
        Going(
            id=run.id or 0,
            moment=moment_of(run),
            action=run.action,
            status=run.status,
            runner=run.runner,
            speaker=speaker or UNKNOWN,
            text=text,
            result=run.result,
        )
        for run, speaker, text in (await db.exec(query)).all()
    ]
