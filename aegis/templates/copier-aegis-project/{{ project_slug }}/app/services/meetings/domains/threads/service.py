"""Commitments, contradictions and positions, read: one meeting's (from
its notes, with what its series keeps coming back to), one person's
across an owner's meetings, and what the owner's earlier meetings leave
for the next notes. Each thread comes with
the transcript lines it cites (``ThreadItem``)."""

from collections.abc import Iterable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.notes import queries as notes_queries
from app.services.meetings.domains.notes.queries import first_lines
from app.services.meetings.domains.notes.service import notes_of
from app.services.meetings.domains.people import queries
from app.services.meetings.domains.series.service import meeting_themes
from app.services.meetings.domains.threads.ledger import (
    Earlier,
    Entry,
    due_line,
    earlier_lines,
    latest_stances,
    ledger,
    stances,
    still_open,
)
from app.services.meetings.domains.threads.ledger import earlier as earlier_text
from app.services.meetings.models import (
    Contradiction,
    Meeting,
    Notes,
    Position,
    Quote,
    ThreadItem,
    ThreadSection,
)
from app.services.meetings.service import MeetingsService

# ponytail: an owner's latest meetings only, so a ledger read and the
# writer's prompt stay bounded; older commitments fall off.
MEETINGS = 50
RAISED = "Came up again"
# The parts of ``Notes`` a thread is read from.
THREADS = ("commitments", "follow_ups", "contradictions", "positions")


async def meeting_threads(svc: MeetingsService, meeting_id: int) -> list[ThreadSection]:
    """The meeting's threads (one ``svc``'s owner can see), each with the
    lines it cites, then what its series keeps coming back to that came
    up in it; empty sections for notes that have none."""
    meeting = await svc.get(meeting_id)  # one the owner cannot see is not found
    kept = (await svc.notes_for([meeting_id])).get(meeting_id)
    notes = (kept.notes if kept else None) or Notes(summary="")
    # Where each earlier commitment raised here was first said.
    first = await first_lines(
        svc.db, [f.commitment for f in notes.follow_ups if f.commitment]
    )
    lines = [
        *(n for c in notes.commitments for n in c.lines),
        *(n for f in notes.follow_ups for n in f.lines),
        *first.values(),
        *(n for c in notes.contradictions for n in [*c.lines, *c.against]),
        *(n for p in notes.positions for n in p.lines),
    ]
    cited = await queries.quotes(svc.db, lines)
    here = meeting_id
    return [
        _section(
            "commitments",
            "Commitments",
            [
                _item(here, c.text, c.lines, cited, speaker=c.owner, detail=due_line(c))
                for c in notes.commitments
            ],
        ),
        _section(
            "follow_ups",
            "Earlier commitments raised",
            [
                _item(
                    here,
                    f.text,
                    f.lines,
                    cited,
                    status=f.status,
                    other=[first[f.commitment]] if f.commitment in first else [],
                )
                for f in notes.follow_ups
            ],
            other="First said",
        ),
        _section(
            "contradictions",
            "Said both ways",
            [_both_ways(here, c, cited) for c in notes.contradictions],
            other="Against",
        ),
        _section(
            "positions",
            "Where people stand",
            [_stance(here, p, cited) for p in notes.positions],
        ),
        await meeting_themes(svc.db, meeting),
    ]


async def person_threads(
    db: AsyncSession, owner_user_id: int | None, person: str
) -> list[ThreadSection]:
    """``person``'s threads across the owner's latest meetings (every
    owner's for None): what they said they would do and what was promised
    them, each with where it came up again and where it stands; where
    they stood on each topic, oldest first; and what they said both ways."""
    kept = await _kept(db, owner_user_id)
    entries = ledger(kept)
    promised = [e for e in entries if e.commitment.owner == person]
    promised_them = [
        e for e in entries if e.commitment.to == person and e.commitment.owner != person
    ]
    positions = [(m, p) for m, p in stances(kept) if p.speaker == person]
    both_ways = [
        (m, c) for m, n in kept for c in n.contradictions if person in c.speakers
    ]
    cited = await queries.quotes(
        db,
        [
            *(n for e in [*promised, *promised_them] for n in _entry_lines(e)),
            *(n for _, p in positions for n in p.lines),
            *(n for _, c in both_ways for n in [*c.lines, *c.against]),
        ],
    )
    return [
        _section(
            "promised",
            "They said they would",
            [_entry(e, cited) for e in promised],
            other=RAISED,
        ),
        _section(
            "promised_them",
            "Promised to them",
            [_entry(e, cited) for e in promised_them],
            other=RAISED,
        ),
        _section(
            "positions",
            "Where they stand",
            [_stance(m, p, cited) for m, p in positions],
        ),
        _section(
            "contradictions",
            "Said both ways",
            [_both_ways(m, c, cited) for m, c in both_ways],
            other="Against",
        ),
    ]


async def earlier(db: AsyncSession, meeting: Meeting, people: list[str]) -> Earlier:
    """What the owner's meetings before ``meeting`` leave for its notes:
    the commitments ``people`` made or were made that are still open, and
    where each of them last stood on each topic, with their lines."""
    kept = [
        (m, n)
        for m, n in await _kept(db, meeting.owner_user_id)
        if m < (meeting.id or 0)
    ]
    open_ = still_open(ledger(kept), people)
    positions = latest_stances(kept, people)
    cited = await queries.quotes(db, earlier_lines(open_, positions))
    return earlier_text(open_, positions, cited)


async def _kept(db: AsyncSession, owner_user_id: int | None) -> list[tuple[int, Notes]]:
    """The threads in the notes of the owner's latest meetings (None: the
    standalone install's, not every owner's), oldest first."""
    ids = await notes_queries.owner_meetings(db, owner_user_id, MEETINGS)
    rows = await notes_of(db, ids, THREADS)
    read = {m: row.notes for m, row in rows.items()}
    return [(m, notes) for m, notes in sorted(read.items()) if notes is not None]


def _entry_lines(entry: Entry) -> list[int]:
    return [*entry.commitment.lines, *(n for _, f in entry.raised for n in f.lines)]


def _entry(entry: Entry, cited: dict[int, Quote]) -> ThreadItem:
    """A commitment with where it stands: the later lines that raised it
    as its other lines."""
    made = entry.commitment
    return _item(
        entry.meeting_id,
        made.text,
        made.lines,
        cited,
        speaker=made.owner,
        detail=due_line(made),
        status=entry.status,
        other=[n for _, f in entry.raised for n in f.lines],
    )


def _stance(meeting_id: int, p: Position, cited: dict[int, Quote]) -> ThreadItem:
    detail = f"{p.topic}, shifted from: {p.shifted}" if p.shifted else p.topic
    return _item(meeting_id, p.text, p.lines, cited, speaker=p.speaker, detail=detail)


def _both_ways(
    meeting_id: int, c: Contradiction, cited: dict[int, Quote]
) -> ThreadItem:
    return _item(
        meeting_id,
        c.text,
        c.lines,
        cited,
        speaker=", ".join(c.speakers) or None,
        other=c.against,
    )


def _item(
    meeting_id: int,
    text: str,
    lines: Iterable[int],
    cited: dict[int, Quote],
    *,
    speaker: str | None = None,
    detail: str | None = None,
    status: str | None = None,
    other: Iterable[int] = (),
) -> ThreadItem:
    return ThreadItem(
        meeting_id=meeting_id,
        text=text,
        speaker=speaker,
        detail=detail,
        status=status,
        quotes=[cited[n] for n in lines if n in cited],
        other=[cited[n] for n in other if n in cited],
    )


def _section(
    key: str, title: str, items: list[ThreadItem], other: str | None = None
) -> ThreadSection:
    return ThreadSection(key=key, title=title, other=other, items=items)
