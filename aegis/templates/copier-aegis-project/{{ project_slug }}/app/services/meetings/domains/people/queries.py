"""The reads (and the few writes) behind people: who a call's names are,
which of them the owner is, what the bot heard of each, each person's
guide and its points, the meetings a person spoke in and what was said
there, and the lines anything cites."""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.notes.queries import with_speaker
from app.services.meetings.models import (
    UNKNOWN,
    Meeting,
    MeetingGuidePoint,
    MeetingGuidePointLine,
    MeetingParticipant,
    MeetingPerson,
    PersonGuide,
    Quote,
    TranscriptLine,
)
from app.services.shared.queries import owner_clause, owner_filters


async def participants_named(
    db: AsyncSession, meeting_id: int, names: Iterable[str]
) -> list[MeetingParticipant]:
    query = select(MeetingParticipant).where(
        MeetingParticipant.meeting_id == meeting_id,
        col(MeetingParticipant.display_name).in_(list(names)),
    )
    return list((await db.exec(query)).all())


async def people_known_as(
    db: AsyncSession, owner_user_id: int | None, names: Iterable[str]
) -> dict[str, int]:
    """The owner's person each of ``names`` already is: one a call named so
    (the latest), else one first named so."""
    wanted = list(names)
    called = (
        select(MeetingParticipant.display_name, MeetingParticipant.person_id)
        .join(Meeting, col(Meeting.id) == MeetingParticipant.meeting_id)
        .where(
            owner_clause(Meeting.owner_user_id, owner_user_id),
            col(MeetingParticipant.display_name).in_(wanted),
        )
        .order_by(col(MeetingParticipant.id))
    )
    first = select(MeetingPerson.name, MeetingPerson.id).where(
        owner_clause(MeetingPerson.owner_user_id, owner_user_id),
        col(MeetingPerson.name).in_(wanted),
    )
    known: dict[str, int] = {
        name: person for name, person in (await db.exec(first)).all() if person
    }
    known |= {name: person for name, person in (await db.exec(called)).all()}
    return known


async def meeting_people(
    db: AsyncSession, meeting_id: int
) -> list[tuple[MeetingParticipant, MeetingPerson]]:
    """Everyone the call named, with the person each is, by name."""
    query = (
        select(MeetingParticipant, MeetingPerson)
        .join(MeetingPerson, col(MeetingPerson.id) == MeetingParticipant.person_id)
        .where(MeetingParticipant.meeting_id == meeting_id)
        .order_by(col(MeetingParticipant.display_name))
    )
    return [(p, person) for p, person in (await db.exec(query)).all()]


async def owner_people(
    db: AsyncSession, owner_user_id: int | None
) -> list[MeetingPerson]:
    query = select(MeetingPerson).where(
        owner_clause(MeetingPerson.owner_user_id, owner_user_id)
    )
    return list((await db.exec(query)).all())


async def my_names(db: AsyncSession, owner_user_id: int | None) -> set[str]:
    """The names of the people the owner is."""
    query = select(MeetingPerson.name).where(
        owner_clause(MeetingPerson.owner_user_id, owner_user_id),
        col(MeetingPerson.is_me).is_(True),
    )
    return set((await db.exec(query)).all())


async def mark_me(db: AsyncSession, person_ids: Iterable[int], is_me: bool) -> None:
    ids = list(person_ids)
    if ids:
        await db.exec(  # type: ignore[call-overload]
            update(MeetingPerson)
            .where(col(MeetingPerson.id).in_(ids))
            .values(is_me=is_me)
        )


async def guides(
    db: AsyncSession, owner_user_id: int | None, limit: int
) -> list[tuple[PersonGuide, MeetingPerson]]:
    """An owner's guides (every owner's for None) with their people,
    latest written first; none of the owner's own (``is_me``)."""
    query = (
        select(PersonGuide, MeetingPerson)
        .join(MeetingPerson, col(MeetingPerson.id) == PersonGuide.person_id)
        .where(
            *owner_filters(MeetingPerson.owner_user_id, owner_user_id),
            col(MeetingPerson.is_me).is_(False),
        )
        .order_by(col(PersonGuide.written_at).desc(), col(PersonGuide.id).desc())
        .limit(limit)
    )
    return [(g, p) for g, p in (await db.exec(query)).all()]


async def guide(
    db: AsyncSession, owner_user_id: int | None, guide_id: int
) -> tuple[PersonGuide, MeetingPerson] | None:
    query = (
        select(PersonGuide, MeetingPerson)
        .join(MeetingPerson, col(MeetingPerson.id) == PersonGuide.person_id)
        .where(
            PersonGuide.id == guide_id,
            *owner_filters(MeetingPerson.owner_user_id, owner_user_id),
        )
    )
    found = (await db.exec(query)).first()
    return None if found is None else (found[0], found[1])


async def guide_row(
    db: AsyncSession, person_id: int, lock: bool = False
) -> PersonGuide | None:
    """The person's guide row; ``lock``: for this transaction, where the
    engine locks rows (Postgres), so two writers take turns."""
    query = select(PersonGuide).where(PersonGuide.person_id == person_id)
    if lock:
        query = query.with_for_update()
    return (await db.exec(query)).first()


async def guide_points(
    db: AsyncSession, guide_ids: list[int]
) -> list[tuple[MeetingGuidePoint, int | None]]:
    """Every point of those guides in order, each once per line it cites
    (in order; None for a point that cites none)."""
    if not guide_ids:
        return []
    query = (
        select(MeetingGuidePoint, MeetingGuidePointLine.line_id)
        .join(
            MeetingGuidePointLine,
            col(MeetingGuidePointLine.point_id) == MeetingGuidePoint.id,
            isouter=True,
        )
        .where(col(MeetingGuidePoint.guide_id).in_(guide_ids))
        .order_by(
            col(MeetingGuidePoint.guide_id),
            col(MeetingGuidePoint.ord),
            col(MeetingGuidePointLine.ord),
        )
    )
    return [(point, line) for point, line in (await db.exec(query)).all()]


async def points_left_uncited(db: AsyncSession, point_ids: list[int]) -> list[int]:
    """Which of ``point_ids`` cite no line any more."""
    if not point_ids:
        return []
    still = select(MeetingGuidePointLine.point_id).where(
        col(MeetingGuidePointLine.point_id).in_(point_ids)
    )
    citing = set((await db.exec(still)).all())
    return [p for p in point_ids if p not in citing]


async def drop_people_in_no_meeting(db: AsyncSession, person_ids: list[int]) -> None:
    """Drop those of ``person_ids`` no meeting has any more, their guides
    with them."""
    if person_ids:
        await db.exec(  # type: ignore[call-overload]
            delete(MeetingPerson).where(
                col(MeetingPerson.id).in_(person_ids),
                col(MeetingPerson.id).not_in(select(MeetingParticipant.person_id)),
            )
        )


async def meetings_with(db: AsyncSession, person_id: int, limit: int) -> list[int]:
    """The meetings ``person_id`` spoke in, newest first."""
    query = (
        select(MeetingParticipant.meeting_id)
        .where(MeetingParticipant.person_id == person_id)
        .distinct()
        .order_by(col(MeetingParticipant.meeting_id).desc())
        .limit(limit)
    )
    return list((await db.exec(query)).all())


def _spoken() -> Any:
    """Each transcript line with its speaker as the call named them, and
    the person that is (None: nobody named)."""
    return with_speaker(
        select(MeetingParticipant.display_name, MeetingPerson, TranscriptLine)
    )


async def said_in(
    db: AsyncSession, meeting_ids: Iterable[int]
) -> list[tuple[int, MeetingPerson | None, TranscriptLine]]:
    """Every line of those meetings: (meeting, the person who said it,
    line), each meeting's in the order it was said."""
    query = (
        _spoken()
        .where(col(TranscriptLine.meeting_id).in_(list(meeting_ids)))
        .order_by(
            col(TranscriptLine.meeting_id),
            col(TranscriptLine.start_seconds),
            col(TranscriptLine.id),
        )
    )
    return [(line.meeting_id, person, line) for _, person, line in await db.exec(query)]


async def quotes(db: AsyncSession, line_ids: Iterable[int]) -> dict[int, Quote]:
    """The lines a note or a guide cites, by id, each with its speaker as
    that call named them."""
    ids = list(line_ids)
    if not ids:
        return {}
    query = _spoken().where(col(TranscriptLine.id).in_(ids))
    return {
        line.id: Quote(
            id=line.id,
            meeting_id=line.meeting_id,
            speaker=name or UNKNOWN,
            at=line.start_seconds,
            text=line.text,
        )
        for name, _, line in await db.exec(query)
    }
