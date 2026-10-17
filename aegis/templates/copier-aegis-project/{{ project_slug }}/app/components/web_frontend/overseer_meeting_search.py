"""The search box on Overseer's Meetings page: every owner's transcripts
and notes searched for the words in the address (``?q=``), each hit
opening its meeting in the drawer at its line (``hit_link``, as Overseer's
chat links it), the words kept so the hits stay above it."""

from typing import Any
from urllib.parse import urlencode

from app.services.meetings.domains.people.service import said_when
from app.services.meetings.domains.search.service import (
    SearchHit,
    hit_link,
    search_meetings,
)

from .overseer_nav import SectionRequest

SEARCH_PARAM = "q"


async def search_context(req: SectionRequest, page: str) -> dict[str, Any]:
    """The box (re-requesting ``page`` as it is typed in), and the hits for
    the words it holds; none until it holds some."""
    words = (req.query.get(SEARCH_PARAM) or "").strip()
    hits = await search_meetings(req.db, None, words) if words else None
    return {
        "search": {
            "url": page,
            "q": words,
            "hits": None if hits is None else [_row(hit, words) for hit in hits],
        }
    }


def _row(hit: SearchHit, words: str) -> dict[str, Any]:
    return {
        "url": f"{hit_link(hit, overseer=True)}&{urlencode({SEARCH_PARAM: words})}",
        "who": hit.speaker or hit.part,
        "when": said_when(hit.meeting_id, hit.at),
        "text": hit.text,
    }
