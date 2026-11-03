"""The reads behind search: the transcript lines and the note items that
match, each with its meeting. Only what matches is the engine's own
(Postgres's full-text search, SQLite's FTS5 tables, ``fts``); the rest is
one query on both. A row matches with any of the words, so a question
asked whole finds the lines that answer it, those with more of its words
first."""

from datetime import datetime
import re
from typing import Any

from sqlalchemy import Integer, case, text
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
# How each engine reads a table's rows (``{table}``) and whether a row has
# the words ``{q}``, and how it joins and quotes them. Postgres reads each
# row's words once (``v``), however many are asked about.
_ENGINES = {
    "postgresql": (
        f"{{table}}, to_tsvector({_ENGLISH}, text) AS v",
        f"v @@ to_tsquery({_ENGLISH}, {{q}})",
        " | ",
        "{}",
    ),
    "sqlite": (
        "{table}",
        "id IN (SELECT rowid FROM {fts} WHERE {fts} MATCH {q})",
        " OR ",
        '"{}"',
    ),
}
# Each table's FTS5 table, on SQLite.
_FTS = {"meeting_transcript_line": LINES, "meeting_note_item": NOTES}
# ponytail: a question's first words only, so the statement stays bounded.
MOST_WORDS = 12
# The order a meeting's notes read in: the summary, then each part.
_READ_ORDER = {kind: place for place, kind in enumerate((SUMMARY, *PARTS))}


def _words(query: str) -> list[str]:
    """The words of ``query``, each once."""
    found = dict.fromkeys(w.lower() for w in re.findall(r"\w+", query))
    return list(found)[:MOST_WORDS]


def _found(db: AsyncSession, table: str, query: str) -> Any:
    """The ids of ``table``'s rows with any of the words of ``query``, each
    with how many of them it has (``score``). Every word is bound alone, so
    nothing in it is syntax: Postgres ORs them in ``to_tsquery``, FTS5 with
    each one quoted."""
    rows, match, either, quote = _ENGINES[db.get_bind().dialect.name]
    asked = {f"w{n}": quote.format(word) for n, word in enumerate(_words(query))}

    def has(q: str) -> str:
        return match.format(fts=_FTS[table], q=q)

    score = " + ".join(f"CASE WHEN {has(f':{w}')} THEN 1 ELSE 0 END" for w in asked)
    sql = f"SELECT id, {score} AS score FROM {rows.format(table=table)} WHERE {has(':any')}"
    found = text(sql).bindparams(any=either.join(asked.values()), **asked)
    return found.columns(id=Integer, score=Integer).subquery("found")


def searchable(query: str) -> bool:
    """Whether ``query`` has a word to search for."""
    return bool(_words(query))


async def lines(
    db: AsyncSession, owner_user_id: int | None, query: str, limit: int
) -> list[tuple[TranscriptLine, str | None, str, datetime, int]]:
    """The owner's lines that match (every owner's for None), those with
    more of the words first, then newest meeting first and each meeting's
    in the order said: (line, speaker, the meeting's link, when it was
    asked for, how many of the words it has)."""
    found = _found(db, "meeting_transcript_line", query)
    statement: Any = (
        select(
            TranscriptLine,
            MeetingParticipant.display_name,
            Meeting.url,
            Meeting.created_at,
            found.c.score,
        )
        .join(found, found.c.id == TranscriptLine.id)
        .join(Meeting, col(Meeting.id) == TranscriptLine.meeting_id)
    )
    statement = (
        with_speaker(statement)
        .where(*owner_filters(Meeting.owner_user_id, owner_user_id))
        .order_by(
            found.c.score.desc(),
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
) -> list[tuple[MeetingNoteItem, str, datetime, int | None, float | None, int]]:
    """The owner's note items that match, those with more of the words
    first, then newest meeting first and each one's in the order its notes
    read: (item, the meeting's link, when it was asked for, the first line
    it cites, when that was said, how many of the words it has)."""
    found = _found(db, "meeting_note_item", query)
    first = first_line()
    statement: Any = (
        select(
            MeetingNoteItem,
            Meeting.url,
            Meeting.created_at,
            first.c.line_id,
            TranscriptLine.start_seconds,
            found.c.score,
        )
        .join(found, found.c.id == MeetingNoteItem.id)
        .join(Meeting, col(Meeting.id) == MeetingNoteItem.meeting_id)
        .join(first, first.c.item_id == MeetingNoteItem.id, isouter=True)
        .join(TranscriptLine, col(TranscriptLine.id) == first.c.line_id, isouter=True)
        .where(*owner_filters(Meeting.owner_user_id, owner_user_id))
        .order_by(
            found.c.score.desc(),
            col(Meeting.created_at).desc(),
            col(Meeting.id).desc(),
            case(_READ_ORDER, value=MeetingNoteItem.kind, else_=len(_READ_ORDER)),
            col(MeetingNoteItem.ord),
        )
        .limit(limit)
    )
    return [tuple(row) for row in (await db.exec(statement)).all()]  # type: ignore[misc]
