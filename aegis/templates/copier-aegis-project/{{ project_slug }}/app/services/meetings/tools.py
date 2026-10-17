"""Meetings' tools (``app.core.tools.load_tools``): search what was said in
the meetings, for Overseer's chat or any agent granted it. Read-only."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.db import get_async_session
from app.core.formatting import format_clock
from app.core.tools import current_owner_user_id, register_tool
from app.services.meetings.domains.search.service import hit_link, search_meetings
from app.services.shared.deps import caller_is_admin


class MeetingHit(BaseModel):
    """One place a search found the words, as the tool hands it over."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    meeting_id: int
    # "Transcript", or the part of the notes ("Summary", "Decisions", ...).
    part: str
    speaker: str | None
    # How far into the call, as a clock reads it ("12:04").
    at: str | None
    text: str
    link: str


async def meetings_search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Search what was said in the user's meetings (an admin's: everyone's)
    and in their notes, by words, not meaning: give the few words that
    would have been said ("pricing", "launch date"), not a question. Newest
    meeting first. A hit is a transcript line (``speaker`` said ``text``,
    ``at`` into the call) or an item of the notes (``part``: Summary,
    Decisions, Action items...). Answer from the lines, quoting who said
    what, and link each line you use with its ``link``."""
    admin = await caller_is_admin()
    owner = None if admin else current_owner_user_id.get()
    async with get_async_session() as session:
        hits = await search_meetings(session, owner, query, min(limit, 50))
    return [
        MeetingHit(
            meeting_id=hit.meeting_id,
            part=hit.part,
            speaker=hit.speaker,
            at=None if hit.at is None else format_clock(hit.at),
            text=hit.text,
            link=hit_link(hit, overseer=admin),
        ).model_dump(mode="json")
        for hit in hits
    ]


register_tool("meetings_search", meetings_search, effect="read")
