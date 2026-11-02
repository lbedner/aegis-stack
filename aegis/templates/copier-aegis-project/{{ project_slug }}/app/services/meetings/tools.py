"""Meetings' tools (``app.core.tools.load_tools``): search what was said in
the meetings, and read how each series stands, for Overseer's chat or any
agent granted them. Read-only."""

from pydantic import BaseModel

from app.core.db import get_async_session
from app.core.figures import FIGURES, absent
from app.core.formatting import format_clock
from app.core.tools import Refused, current_owner_user_id, register_tool
from app.services.meetings.domains.search.service import hit_link, search_meetings
from app.services.meetings.domains.series.kept import notes_of
from app.services.meetings.domains.series.service import (
    SeriesNotFoundError,
    SeriesService,
    series_name,
)
from app.services.meetings.models import OVER_TIME, MeetingSeries
from app.services.shared.deps import caller_is_admin


class MeetingHit(BaseModel):
    """One place a search found the words, as the tool hands it over."""

    model_config = FIGURES

    meeting_id: int
    # "Transcript", or the part of the notes ("Summary", "Decisions", ...).
    part: str
    speaker: str | None
    # How far into the call, as a clock reads it ("12:04").
    at: str | None
    text: str
    link: str


async def meetings_search(query: str, limit: int = 20) -> list[MeetingHit]:
    """Search what was said in the user's meetings (an admin's: everyone's)
    and in their notes, by words, not meaning: give the few words that
    would have been said ("pricing", "launch date"), not a question. Newest
    meeting first. A hit is a transcript line (``speaker`` said ``text``,
    ``at`` into the call) or an item of the notes (``part``: Summary,
    Decisions, Action items...). Answer from the lines, quoting who said
    what, and link each line you use with its ``link``."""
    admin, owner = await _reader()
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
        )
        for hit in hits
    ]


class SeriesBrief(BaseModel):
    """One series of meetings: a recurring meeting over time."""

    model_config = FIGURES

    series_id: int
    name: str
    # How many of its meetings it was last read from.
    meetings: int
    # The day it was last written, after its latest meeting (ISO).
    updated: str
    # One sentence: where the series stands now.
    headline: str


class SeriesTheme(BaseModel):
    """Something the series keeps coming back to, and where it stands."""

    model_config = FIGURES

    text: str
    status: str


class SeriesRead(SeriesBrief):
    """A series in full; a part with nothing in it is left out."""

    themes: list[SeriesTheme] | None = absent()
    settled: list[str] | None = absent()
    shifted: list[str] | None = absent()
    still_open: list[str] | None = absent()
    mood: list[str] | None = absent()


async def meetings_series(
    series_id: int | None = None,
) -> list[SeriesBrief] | SeriesRead | Refused:
    """The user's series of meetings (an admin's: everyone's), each a
    recurring meeting read over time: without ``series_id``, every series
    with its headline, latest first; with it, that series in full: what it
    keeps coming back to (each theme open, answered or done), what was
    settled, what shifted, what is still open, and the mood. Read the
    series to say how one is going or to summarize it; search the words
    said (``meetings_search``) for one thing in particular."""
    _, owner = await _reader()
    async with get_async_session() as session:
        svc = SeriesService(session, owner)
        if series_id is None:
            return [_brief(row.series, row.name) for row in await svc.series()]
        try:
            series = await svc.get(series_id)
        except SeriesNotFoundError as exc:
            return Refused(error=str(exc))
        notes = await notes_of(session, series)
    texts = {part: [p.text for p in getattr(notes, part)] or None for part in OVER_TIME}
    themes = [SeriesTheme(text=t.text, status=t.status) for t in notes.themes]
    brief = _brief(series, series_name(series)).model_dump()
    return SeriesRead(**brief, themes=themes or None, **texts)


def _brief(series: MeetingSeries, name: str) -> SeriesBrief:
    return SeriesBrief(
        series_id=series.id,  # type: ignore[arg-type]
        name=name,
        meetings=series.meetings,
        updated=series.written_at.date().isoformat(),
        headline=series.summary,
    )


async def _reader() -> tuple[bool, int | None]:
    """Whether the caller is an admin, and whose meetings they read (None:
    every owner's)."""
    admin = await caller_is_admin()
    return admin, None if admin else current_owner_user_id.get()


register_tool(
    "meetings_series",
    meetings_series,
    effect="read",
    doing="Reading the series",
)
register_tool(
    "meetings_search",
    meetings_search,
    effect="read",
    doing="Searching the meetings",
)
