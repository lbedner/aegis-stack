"""Each person's guide, read and kept for one owner (``owner_user_id``;
``None`` reads every owner's, as Overseer does): how to work with them,
each point with the lines it rests on, and the owner's own note on them."""

from collections.abc import Callable, Coroutine
import importlib
from importlib.util import find_spec
from types import ModuleType
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.concurrency import background
from app.core.formatting import format_clock
from app.services.meetings.domains.people import queries
from app.services.meetings.models import (
    GUIDE_SECTIONS,
    Guide,
    GuidePoint,
    GuideRecord,
    GuideSection,
    PersonGuide,
    Quote,
)
from app.services.meetings.service import NothingToWriteError

# The model pass that writes a guide: only a stack with a model to ask has
# the module.
GUIDES = "app.services.meetings.domains.people.guides"
# The guides this process is writing now, by (owner, person).
GUIDING: set[tuple[int | None, str]] = set()
LIMIT = 200


class GuideNotFoundError(LookupError):
    """No such guide for this owner."""


class PeopleService:
    def __init__(self, db: AsyncSession, owner_user_id: int | None) -> None:
        self.db = db
        self.owner_user_id = owner_user_id

    async def guides(self) -> list[PersonGuide]:
        """The owner's guides, latest written first."""
        return await queries.guides(self.db, self.owner_user_id, LIMIT)

    async def get(self, guide_id: int) -> PersonGuide:
        found = await queries.guide(self.db, self.owner_user_id, guide_id)
        if found is None:
            raise GuideNotFoundError(f"Guide {guide_id} not found")
        return found

    async def read(self, guide_id: int) -> GuideRecord:
        """The guide in full: each part, its points with the lines they
        rest on."""
        return await self._record(await self.get(guide_id))

    async def _record(self, kept: PersonGuide) -> GuideRecord:
        guide = kept.guide() or Guide()
        cited = await queries.quotes(
            self.db, {line for point in guide.points() for line in point.lines}
        )
        writing = (kept.owner_user_id, kept.person) in GUIDING
        return GuideRecord(
            guide=kept,
            sections=[_section(guide, key, cited) for key in GUIDE_SECTIONS],
            writing=writing,
            can_write=guide_writer() is not None and not writing,
        )

    async def set_note(self, guide_id: int, note: str) -> GuideRecord:
        """The owner's own note on the person (blank clears it), kept
        across every rewrite and read with the meetings when it is; the
        guide read with it."""
        kept = await self.get(guide_id)
        kept.note = note.strip() or None
        self.db.add(kept)
        await self.db.commit()
        return await self._record(kept)

    async def write_again(self, guide_id: int) -> GuideRecord:
        """Start writing the guide over from every meeting, in the
        background; the read it returns says it is being written."""
        record = await self.read(guide_id)
        write = guide_writer()
        if write is None or not record.can_write:
            raise NothingToWriteError("This guide cannot be written now")
        kept = record.guide
        GUIDING.add((kept.owner_user_id, kept.person))
        background(write(kept.owner_user_id, kept.person))
        return record.model_copy(update={"writing": True, "can_write": False})


def said_when(meeting_id: int, at: float) -> str:
    """Where a cited line was said, as the pages label it."""
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


def _guides() -> ModuleType | None:
    return importlib.import_module(GUIDES) if find_spec(GUIDES) else None


def guide_writer() -> Callable[[int | None, str], Coroutine[Any, Any, None]] | None:
    """What writes one person's guide, where the stack has a model to."""
    module = _guides()
    return None if module is None else module.write_guide


def guides_writer() -> Callable[[int], Coroutine[Any, Any, None]] | None:
    """What writes the guide of everyone in a meeting but the owner."""
    module = _guides()
    return None if module is None else module.write_guides
