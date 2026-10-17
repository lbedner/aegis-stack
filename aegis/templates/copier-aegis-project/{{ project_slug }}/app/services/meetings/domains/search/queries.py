"""The reads behind search: the transcript lines and the note items that
match, each with its meeting. Only what matches is the engine's own
(Postgres's full-text search, SQLite's FTS5 tables, ``fts``); the rest is
one query on both."""

from datetime import datetime
import re
from typing import Any

from sqlalchemy import Integer, TextClause, case, text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.notes.queries import first_line, with_speaker
from app.services.meetings.domains.notes.service import PARTS, SUMMARY
from app.services.meetings.domains.search.fts import LINES, NOTES
from app.services.meetings.models import (
    Meeting,
    MeetingNoteItem,
    MeetingParticipant,
    TranscriptLine,
)
from app.services.shared.queries import owner_filters

_ENGLISH = "'english'::regconfig"
_PG_MATCH = f"to_tsvector({_ENGLISH}, {{}}) @@ websearch_to_tsquery({_ENGLISH}, :query)"

# The ids of the lines that match, by engine.
_LINES = {
    "postgresql": "SELECT id FROM meeting_transcript_line WHERE "
    + _PG_MATCH.format("text"),
    "sqlite": f"SELECT rowid AS id FROM {LINES} WHERE {LINES} MATCH :query",
}
# The ids of the note items that match, by engine.
_NOTES = {
    "postgresql": "SELECT id FROM meeting_note_item WHERE " + _PG_MATCH.format("text"),
    "sqlite": f"SELECT rowid AS id FROM {NOTES} WHERE {NOTES} MATCH :query",
}
# The order a meeting's notes read in: the summary, then each part.
_READ_ORDER = {kind: place for place, kind in enumerate((SUMMARY, *PARTS))}


def _words(query: str) -> str:
    """``query`` as FTS5 reads it: every word, each quoted so nothing in it
    is syntax, all of them to match."""
    return " ".join(f'"{word}"' for word in re.findall(r"\w+", query))


def _matching(db: AsyncSession, sql: dict[str, str], query: str) -> TextClause:
    engine = db.get_bind().dialect.name
    asked = query if engine == "postgresql" else _words(query)
    return text(sql[engine]).bindparams(query=asked)


def searchable(query: str) -> bool:
    """Whether ``query`` has a word to search for."""
    return bool(re.search(r"\w", query))


async def lines(
    db: AsyncSession, owner_user_id: int | None, query: str, limit: int
) -> list[tuple[TranscriptLine, str | None, str, datetime]]:
    """The owner's lines that match (every owner's for None), newest
    meeting first and each meeting's in the order said: (line, speaker,
    the meeting's link, when it was asked for)."""
    found = _matching(db, _LINES, query).columns(id=Integer).subquery("found")
    statement: Any = (
        select(
            TranscriptLine,
            MeetingParticipant.display_name,
            Meeting.url,
            Meeting.created_at,
        )
        .join(found, found.c.id == TranscriptLine.id)
        .join(Meeting, col(Meeting.id) == TranscriptLine.meeting_id)
    )
    statement = (
        with_speaker(statement)
        .where(*owner_filters(Meeting.owner_user_id, owner_user_id))
        .order_by(
            col(Meeting.created_at).desc(),
            col(Meeting.id).desc(),
            col(TranscriptLine.start_seconds),
            col(TranscriptLine.id),
        )
        .limit(limit)
    )
    return list((await db.exec(statement)).all())  # type: ignore[arg-type]


async def notes(
    db: AsyncSession, owner_user_id: int | None, query: str, limit: int
) -> list[tuple[MeetingNoteItem, str, datetime, int | None, float | None]]:
    """The owner's note items that match, newest meeting first and each
    one's in the order its notes read: (item, the meeting's link, when it
    was asked for, the first line it cites and when that was said)."""
    found = _matching(db, _NOTES, query).columns(id=Integer).subquery("found")
    first = first_line()
    statement: Any = (
        select(
            MeetingNoteItem,
            Meeting.url,
            Meeting.created_at,
            first.c.line_id,
            TranscriptLine.start_seconds,
        )
        .join(found, found.c.id == MeetingNoteItem.id)
        .join(Meeting, col(Meeting.id) == MeetingNoteItem.meeting_id)
        .join(first, first.c.item_id == MeetingNoteItem.id, isouter=True)
        .join(TranscriptLine, col(TranscriptLine.id) == first.c.line_id, isouter=True)
        .where(*owner_filters(Meeting.owner_user_id, owner_user_id))
        .order_by(
            col(Meeting.created_at).desc(),
            col(Meeting.id).desc(),
            case(_READ_ORDER, value=MeetingNoteItem.kind, else_=len(_READ_ORDER)),
            col(MeetingNoteItem.ord),
        )
        .limit(limit)
    )
    return [tuple(row) for row in (await db.exec(statement)).all()]  # type: ignore[misc]
