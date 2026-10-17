"""A meeting's notes, kept as rows and read back as ``Notes``: each item in
its part (``kind``, a ``Notes`` field) and place, citing its lines in
order, each name the model gave beside the person it was found to be.

Notes written again keep each commitment that cites a line it cited
before, so what later meetings said of it (their follow-ups) still points
at it; a pass that fails keeps the notes it had, with why.
"""

from collections.abc import Iterable
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.meetings.domains.notes import queries
from app.services.meetings.domains.notes.queries import COMMITMENTS
from app.services.meetings.domains.people.participants import named
from app.services.meetings.models import (
    ActionItem,
    Commitment,
    Contradiction,
    FollowUp,
    KeptNotes,
    Meeting,
    MeetingNoteItem,
    MeetingNoteLine,
    MeetingNotes,
    NoteItem,
    Notes,
    Position,
)

SUMMARY = "summary"
# The parts of ``Notes`` kept as items, in the order they read.
PARTS = tuple(name for name in Notes.model_fields if name != SUMMARY)


def _names(notes: Notes) -> set[str]:
    """Every name the model gave in ``notes``."""
    found = {a.owner for a in notes.action_items}
    found |= {n for c in notes.commitments for n in (c.owner, c.to)}
    found |= {p.speaker for p in notes.positions}
    return {n for n in found if n}


def _columns(item: NoteItem, who: dict[str, int | None]) -> dict[str, Any]:
    """The columns past ``text`` that ``item``'s kind has."""
    owner = getattr(item, "owner", None) or getattr(item, "speaker", None)
    to = getattr(item, "to", None)
    return {
        "person_id": who.get(owner) if owner else None,
        "person_text": owner,
        "to_person_id": who.get(to) if to else None,
        "to_text": to,
        "due": getattr(item, "due", None),
        "topic": getattr(item, "topic", None),
        "shifted": getattr(item, "shifted", None),
        "status": getattr(item, "status", None),
        "commitment_id": getattr(item, "commitment", None),
    }


def _same(lines: list[int], before: dict[int, set[int]], taken: set[int]) -> int | None:
    """The earlier commitment sharing the most lines with ``lines``, if
    any shares one and no other commitment took it."""
    best = max(
        (i for i in before if i not in taken and before[i] & set(lines)),
        key=lambda i: len(before[i] & set(lines)),
        default=None,
    )
    if best is not None:
        taken.add(best)
    return best


async def keep_notes(
    db: AsyncSession, meeting_id: int, notes: Notes, model_name: str | None
) -> None:
    """Keep ``notes`` as the meeting's, over any it had. A follow-up's
    ``commitment`` is the commitment's own id; citations of lines (or
    commitments) that no longer exist are left out."""
    meeting: Meeting = await db.get_one(Meeting, meeting_id)
    row = await queries.locked_notes(db, meeting_id) or MeetingNotes(
        meeting_id=meeting_id
    )
    who = await named(db, meeting, _names(notes))
    before = await queries.commitment_lines(db, meeting_id)
    old = {i.id: i for i in await queries.items_of(db, [meeting_id])}
    taken: set[int] = set()
    parts = [(SUMMARY, [NoteItem(text=notes.summary)])]
    parts += [(kind, getattr(notes, kind)) for kind in PARTS]
    rows: list[tuple[MeetingNoteItem, NoteItem]] = []
    for kind, items in parts:
        for place, item in enumerate(items):
            same = _same(item.lines, before, taken) if kind == COMMITMENTS else None
            values = {
                "meeting_id": meeting_id,
                "kind": kind,
                "ord": place,
                "text": item.text,
                **_columns(item, who),
            }
            kept = (
                MeetingNoteItem(**values)
                if same is None
                else old[same].sqlmodel_update(values)
            )
            rows.append((kept, item))
    lines, commitments = await queries.existing(
        db,
        (n for _, i in rows for n in [*i.lines, *getattr(i, "against", [])]),
        (k.commitment_id for k, _ in rows if k.commitment_id),
    )
    await queries.delete_in(db, MeetingNoteItem.id, old.keys() - taken)
    await queries.delete_in(db, MeetingNoteLine.item_id, taken)
    for kept, _ in rows:
        if kept.commitment_id not in commitments:
            kept.commitment_id = None
    db.add_all(kept for kept, _ in rows)
    await db.flush()
    db.add_all(_citations(rows, lines))
    row.error, row.model_name, row.written_at = None, model_name, utcnow()
    db.add(row)
    await db.commit()


def cited(ids: list[int], lines: set[int]) -> list[int]:
    """The lines ``ids`` cite as kept: each once, in order, only those of
    ``lines`` (the ones that still exist)."""
    return list(dict.fromkeys(n for n in ids if n in lines))


def _citations(
    rows: list[tuple[MeetingNoteItem, NoteItem]], lines: set[int]
) -> list[MeetingNoteLine]:
    """Each line each item cites, in order, once; a contradiction's other
    side as ``against``."""
    found = []
    for kept, item in rows:
        for against, ids in ((False, item.lines), (True, getattr(item, "against", []))):
            found += [
                MeetingNoteLine(item_id=kept.id, line_id=n, against=against, ord=i)
                for i, n in enumerate(cited(ids, lines))
            ]
    return found


async def keep_failure(db: AsyncSession, meeting_id: int, error: str) -> None:
    """Why the meeting's notes could not be written; the ones it had stay."""
    row = await queries.locked_notes(db, meeting_id) or MeetingNotes(
        meeting_id=meeting_id
    )
    row.error = error[:500]
    db.add(row)
    await db.commit()


async def notes_of(
    db: AsyncSession, meeting_ids: list[int], parts: Iterable[str] | None = None
) -> dict[int, KeptNotes]:
    """The notes of those meetings read back, by meeting id: only the
    meetings that have notes (or a failure) kept; only ``parts`` of them,
    if given."""
    if not meeting_ids:
        return {}
    rows = await queries.notes_rows(db, meeting_ids)
    items = await queries.items_of(db, meeting_ids, parts)
    cited = await queries.cited(db, [i.id for i in items])  # type: ignore[misc]
    names = await queries.person_names(
        db, (n for i in items for n in (i.person_id, i.to_person_id) if n)
    )
    lines: dict[int, list[tuple[MeetingNoteLine, str | None]]] = {}
    for line, speaker in cited:
        lines.setdefault(line.item_id, []).append((line, speaker))
    by_meeting: dict[int, list[MeetingNoteItem]] = {}
    for item in items:
        by_meeting.setdefault(item.meeting_id, []).append(item)
    return {
        row.meeting_id: KeptNotes(
            notes=_read(by_meeting[row.meeting_id], lines, names)
            if row.meeting_id in by_meeting
            else None,
            error=row.error,
            model_name=row.model_name,
            written_at=row.written_at,
        )
        for row in rows
    }


def _read(
    items: list[MeetingNoteItem],
    lines: dict[int, list[tuple[MeetingNoteLine, str | None]]],
    names: dict[int, str],
) -> Notes:
    """One meeting's items as the ``Notes`` they were written as."""
    notes = Notes(summary="")
    for kept in items:
        if kept.kind == SUMMARY:
            notes.summary = kept.text
        elif kept.kind in PARTS:
            getattr(notes, kept.kind).append(_item(kept, lines.get(kept.id, []), names))  # type: ignore[arg-type]
    return notes


def _item(
    kept: MeetingNoteItem,
    cited: list[tuple[MeetingNoteLine, str | None]],
    names: dict[int, str],
) -> NoteItem:
    """One kept item as its part reads it: names as the people they were
    found to be, else as written."""
    own = [line.line_id for line, _ in cited if not line.against]
    person = names.get(kept.person_id, kept.person_text)
    to = names.get(kept.to_person_id, kept.to_text)
    shared: dict[str, Any] = {"id": kept.id, "text": kept.text, "lines": own}
    if kept.kind == "action_items":
        return ActionItem(**shared, owner=person, due=kept.due)
    if kept.kind == COMMITMENTS:
        return Commitment(**shared, owner=person, to=to, due=kept.due)
    if kept.kind == "follow_ups":
        return FollowUp(
            **shared, commitment=kept.commitment_id, status=kept.status or "mentioned"
        )  # type: ignore[arg-type]
    if kept.kind == "contradictions":
        other = [(line, s) for line, s in cited if line.against]
        sides = [*((line, s) for line, s in cited if not line.against), *other]
        speakers = list(dict.fromkeys(s for _, s in sides if s))
        against = [line.line_id for line, _ in other]
        return Contradiction(**shared, against=against, speakers=speakers)
    if kept.kind == "positions":
        return Position(
            **shared, speaker=person or "", topic=kept.topic or "", shifted=kept.shifted
        )
    return NoteItem(**shared)
