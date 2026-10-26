"""What a line of a call is about, as Illiana says it to whoever asked
(``ask_ai.about``): from the lines either side of it, to the one who asked
alone. Nothing is kept. A line that names a part of the system
(``parts_named``) offers what that part is, the part riding the ask."""

import asyncio
from itertools import groupby
from typing import TYPE_CHECKING

from app.core.discovery import optional
from app.services.meetings.domains.actions.heard import heard_here
from app.services.meetings.domains.actions.prompt import around
from app.services.meetings.domains.actions.registry import ASK_ILLIANA
from app.services.meetings.domains.moments import queries as moments_queries
from app.services.meetings.models import LineAbout, TranscriptRow

if TYPE_CHECKING:
    from app.services.meetings.service import MeetingsService


def asks_about() -> bool:
    """Whether a line can be asked what it is about: where the stack has
    Illiana."""
    return optional(ASK_ILLIANA, "about") is not None


async def parts_named(lines: list[TranscriptRow]) -> dict[int, list[tuple[str, str]]]:
    """The parts of the system each line names, by line id: each part and
    the name it was heard by, once a turn (a speaker's lines in a row)."""
    hears = await asyncio.to_thread(heard_here)
    named: dict[int, list[tuple[str, str]]] = {}
    for _, rows in groupby(lines, key=lambda row: row.speaker):
        seen: set[str] = set()
        for row in rows:
            new = [(p, name) for p, name in hears.named(row.text) if p not in seen]
            seen.update(p for p, _ in new)
            if new:
                named[row.id] = new
    return named


async def line_about(
    svc: "MeetingsService", meeting_id: int, line_id: int, part: str | None = None
) -> LineAbout | None:
    """What a line of one of ``svc``'s meetings is about, as Illiana says it
    to the meeting's owner, from the lines either side of it; asked through
    every owner's meetings (Overseer), as an admin. ``part``, a part the
    line names (``parts_named``), is what she is asked about, where it is
    one this stack's talk can name. None where the stack has no Illiana or
    the meeting no such line."""
    ask = optional(ASK_ILLIANA, "about")
    if ask is None:
        return None
    meeting = await svc.get(meeting_id)
    found = around(await moments_queries.said(svc.db, meeting_id), line_id)
    if found is None:
        return None
    admin = True if svc.owner_user_id is None else None
    known = (await asyncio.to_thread(heard_here)).ids if part else frozenset()
    return await ask(
        *found,
        owner_user_id=meeting.owner_user_id,
        admin=admin,
        part=part if part in known else None,
    )
