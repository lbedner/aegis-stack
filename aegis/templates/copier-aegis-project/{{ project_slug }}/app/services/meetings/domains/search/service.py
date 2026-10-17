"""Search across one owner's meetings (``owner_user_id``; ``None`` searches
every owner's, as Overseer does): every transcript line and every part of
the notes that has the words, each with its meeting, who said it and when,
and the transcript line it opens at. By words, not meaning."""

from datetime import datetime

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.search import queries
from app.services.meetings.models import UNKNOWN
from app.services.meetings.service import status_label

LIMIT = 50
TRANSCRIPT = "Transcript"
# Overseer's Meetings page: ``MEETING_PARAM`` opens one in the drawer,
# ``LINE_PARAM`` at that transcript line (``overseer_meetings`` reads both).
OVERSEER = "/overseer/services/meetings"
MEETING_PARAM = "meeting"
LINE_PARAM = "line"


class SearchHit(BaseModel):
    """One place the words were found: a transcript line, or an item of the
    notes, opening at the line it came from when it cites one."""

    meeting_id: int
    # The call's link and when the bot was asked in: how the pages name it.
    meeting_url: str
    requested_at: datetime
    # "Transcript", or the part of the notes ("Summary", "Decisions", ...).
    part: str
    # Who said it; None for the notes.
    speaker: str | None
    # The transcript line it opens at, and how far into the call (seconds).
    line_id: int | None
    at: float | None
    text: str


def hit_link(hit: SearchHit, overseer: bool) -> str:
    """Where a hit opens: Overseer's drawer (an admin's), else the owner's
    own Meetings page; at its line when it has one."""
    if overseer:
        line = f"&{LINE_PARAM}={hit.line_id}" if hit.line_id else ""
        return f"{OVERSEER}?{MEETING_PARAM}={hit.meeting_id}{line}"
    line = f"#line-{hit.line_id}" if hit.line_id else ""
    return f"/meetings/{hit.meeting_id}{line}"


async def search_meetings(
    db: AsyncSession, owner_user_id: int | None, query: str, limit: int = LIMIT
) -> list[SearchHit]:
    """What the owner's meetings said with the words of ``query``: newest
    meeting first, each one's notes before its lines, its lines in the
    order said."""
    if not queries.searchable(query):
        return []
    said = [
        SearchHit(
            meeting_id=line.meeting_id,
            meeting_url=url,
            requested_at=requested,
            part=TRANSCRIPT,
            speaker=speaker or UNKNOWN,
            line_id=line.id,
            at=line.start_seconds,
            text=line.text,
        )
        for line, speaker, url, requested in await queries.lines(
            db, owner_user_id, query, limit
        )
    ]
    noted = await _noted(db, owner_user_id, query, limit)
    # Stable: within a meeting the notes stay first, the lines as said.
    hits = sorted(
        [*noted, *said], key=lambda h: (h.requested_at, h.meeting_id), reverse=True
    )
    return hits[:limit]


async def _noted(
    db: AsyncSession, owner_user_id: int | None, query: str, limit: int
) -> list[SearchHit]:
    """The items of the notes that have the words, in the order the notes
    read, each at the first line it cites."""
    return [
        SearchHit(
            meeting_id=item.meeting_id,
            meeting_url=url,
            requested_at=requested,
            part=status_label(item.kind),
            speaker=None,
            line_id=line_id,
            at=at,
            text=item.text,
        )
        for item, url, requested, line_id, at in await queries.notes(
            db, owner_user_id, query, limit
        )
    ]
