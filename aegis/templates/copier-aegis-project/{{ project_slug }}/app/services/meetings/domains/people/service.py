"""Each person's guide, read and kept for one owner (``owner_user_id``;
``None`` reads every owner's, as Overseer does): how to work with them,
each point with the lines it rests on, and the owner's own note on them."""

from collections.abc import Callable, Coroutine
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.concurrency import background
from app.core.discovery import optional
from app.core.formatting import format_clock
from app.services.meetings.domains.people import queries
from app.services.meetings.domains.people.kept import guides_of
from app.services.meetings.domains.threads.service import person_threads
from app.services.meetings.models import (
    GUIDE_SECTIONS,
    Guide,
    GuidePoint,
    GuideRecord,
    GuideRow,
    GuideSection,
    MeetingPerson,
    PersonGuide,
    Quote,
)
from app.services.meetings.service import NothingToWriteError

# The model pass that writes a guide: only a stack with a model to ask has
# the module.
GUIDES = "app.services.meetings.domains.people.guides"
# The people whose guides this process is writing now.
GUIDING: set[int] = set()
LIMIT = 200


class GuideNotFoundError(LookupError):
    """No such guide for this owner."""


class PeopleService:
    def __init__(self, db: AsyncSession, owner_user_id: int | None) -> None:
        self.db = db
        self.owner_user_id = owner_user_id

    async def guides(self) -> list[GuideRow]:
        """The owner's guides, latest written first."""
        found = await queries.guides(self.db, self.owner_user_id, LIMIT)
        return [
            GuideRow(guide=g, person=p.name, owner_user_id=p.owner_user_id)
            for g, p in found
        ]

    async def get(self, guide_id: int) -> tuple[PersonGuide, MeetingPerson]:
        found = await queries.guide(self.db, self.owner_user_id, guide_id)
        if found is None:
            raise GuideNotFoundError(f"Guide {guide_id} not found")
        return found

    async def read(self, guide_id: int) -> GuideRecord:
        """The guide in full: each part, its points with the lines they
        rest on, and the person's threads (open threads with you)."""
        return await self._record(*await self.get(guide_id))

    async def _record(self, kept: PersonGuide, person: MeetingPerson) -> GuideRecord:
        guide = (await guides_of(self.db, [kept.id]))[kept.id]  # type: ignore[index,list-item]
        cited = await queries.quotes(
            self.db, {line for point in guide.points() for line in point.lines}
        )
        writing = person.id in GUIDING
        return GuideRecord(
            guide=kept,
            person=person.name,
            owner_user_id=person.owner_user_id,
            sections=[_section(guide, key, cited) for key in GUIDE_SECTIONS],
            writing=writing,
            can_write=guide_writer() is not None and not writing,
            threads=await person_threads(self.db, person.owner_user_id, person.name),
        )

    async def set_note(self, guide_id: int, note: str) -> GuideRecord:
        """The owner's own note on the person (blank clears it), kept
        across every rewrite and read with the meetings when it is; the
        guide read with it."""
        kept, person = await self.get(guide_id)
        kept.note = note.strip() or None
        self.db.add(kept)
        await self.db.commit()
        return await self._record(kept, person)

    async def write_again(self, guide_id: int) -> GuideRecord:
        """Start writing the guide over from every meeting, in the
        background; the read it returns says it is being written."""
        record = await self.read(guide_id)
        write = guide_writer()
        if write is None or not record.can_write:
            raise NothingToWriteError("This guide cannot be written now")
        person_id = record.guide.person_id
        GUIDING.add(person_id)
        background(write(person_id))
        return record.model_copy(update={"writing": True, "can_write": False})


def said_when(meeting_id: int, at: float | None) -> str:
    """Where a cited line was said, as the pages label it (only its
    meeting when not when in it)."""
    if at is None:
        return f"Meeting {meeting_id}"
    return f"Meeting {meeting_id}, {format_clock(at)}"


def _section(guide: Guide, key: str, cited: dict[int, Quote]) -> GuideSection:
    """One part of ``guide``, each point with the lines it rests on."""
    return GuideSection(
        key=key,
        title=GUIDE_SECTIONS[key],
        points=[
            GuidePoint(text=i.text, quotes=[cited[n] for n in i.lines if n in cited])
            for i in getattr(guide, key)
        ],
    )


def guide_writer() -> Callable[[int], Coroutine[Any, Any, None]] | None:
    """What writes one person's guide, where the stack has a model to."""
    return optional(GUIDES, "write_guide")


def guides_writer() -> Callable[[int], Coroutine[Any, Any, None]] | None:
    """What writes the guide of everyone in a meeting but the owner."""
    return optional(GUIDES, "write_guides")
