"""The ledger of commitments across an owner's meetings, and what the
next meeting's notes are written with. Pure: the reads are ``service``'s.

A commitment is known by its own id. The next notes are shown
the open ones numbered ``[C1]``, ``[C2]``...; a follow-up names one by
that number, which ``cited`` turns back into its id.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.services.meetings.models import (
    Commitment,
    FollowUp,
    Notes,
    Position,
    Quote,
)

OPEN = "open"
# A commitment past these is not raised with the next notes.
SETTLED = ("done", "dropped")


@dataclass
class Entry:
    """A commitment, the meeting it was made in, and each later meeting
    that raised it again (oldest first)."""

    meeting_id: int
    commitment: Commitment
    raised: list[tuple[int, FollowUp]] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.raised[-1][1].status if self.raised else OPEN


@dataclass(frozen=True)
class Earlier:
    """What the owner's earlier meetings leave for the next notes: the
    text put before the transcript, the lines it quotes (a contradiction
    may cite them) and the ids of the commitments it numbers (a follow-up
    may name one: ``[C1]`` is the first)."""

    text: str = ""
    lines: frozenset[int] = frozenset()
    commitments: tuple[int, ...] = ()


def ledger(kept: Iterable[tuple[int, Notes]]) -> list[Entry]:
    """Every commitment in ``kept`` (meeting id and notes, oldest first),
    each with the later meetings that raised it."""
    entries: dict[int, Entry] = {}
    for meeting_id, notes in kept:
        for follow in notes.follow_ups:
            if follow.commitment in entries:
                entries[follow.commitment].raised.append((meeting_id, follow))
        for made in notes.commitments:
            if made.id is not None:
                entries[made.id] = Entry(meeting_id, made)
    return list(entries.values())


def stances(kept: Iterable[tuple[int, Notes]]) -> list[tuple[int, Position]]:
    """Every position in ``kept`` with its meeting, oldest first."""
    return [(meeting_id, p) for meeting_id, notes in kept for p in notes.positions]


def latest_stances(
    kept: Iterable[tuple[int, Notes]], people: Iterable[str]
) -> list[Position]:
    """Where each of ``people`` last stood on each topic."""
    wanted = set(people)
    latest = {
        (p.speaker, p.topic.casefold()): p
        for _, p in stances(kept)
        if p.speaker in wanted and p.lines
    }
    return list(latest.values())


def still_open(entries: Iterable[Entry], people: Iterable[str]) -> list[Entry]:
    """The commitments not done or dropped that ``people`` made or were
    made."""
    wanted = set(people)
    return [
        e
        for e in entries
        if e.status not in SETTLED
        and (e.commitment.owner in wanted or e.commitment.to in wanted)
    ]


def earlier_lines(open_: list[Entry], positions: list[Position]) -> set[int]:
    """The lines the earlier text quotes: each open commitment's first,
    and every line of each stance."""
    return {e.commitment.lines[0] for e in open_ if e.commitment.lines} | {
        n for p in positions for n in p.lines
    }


def earlier(
    open_: list[Entry], positions: list[Position], quotes: dict[int, Quote]
) -> Earlier:
    """The earlier text for the notes writer: the open commitments, each
    numbered ``[C<n>]``, the latest stances, and the lines they rest on."""
    if not open_ and not positions:
        return Earlier()
    said = ["Earlier, in meetings before this one:"]
    if open_:
        said.append("Commitments still open:")
        said += [f"[C{n}] {_commitment(e.commitment)}" for n, e in enumerate(open_, 1)]
    if positions:
        said.append("Where people stood:")
        said += [f"{p.speaker} on {p.topic}: {p.text}" for p in positions]
    said.append("The lines they rest on:")
    said += [f"[{q.id}] {q.speaker}: {q.text}" for q in quotes.values()]
    return Earlier(
        text="\n".join(said),
        lines=frozenset(quotes),
        commitments=tuple(e.commitment.id for e in open_),
    )


def _commitment(made: Commitment) -> str:
    detail = due_line(made)
    return f"{made.owner}: {made.text}" + (f" ({detail})" if detail else "")


def due_line(made: Commitment) -> str | None:
    """For whom and by when, as the pages and the writer say it."""
    parts = [f"for {made.to}" if made.to else "", f"by {made.due}" if made.due else ""]
    return ", ".join(p for p in parts if p) or None


def cited(notes: Notes, said: set[int | None], earlier: Earlier) -> Notes:
    """``notes``' threads citing only lines the model was shown (this
    meeting's ``said``, and for a contradiction's other side the earlier
    lines too), and following up only commitments it was shown, each
    follow-up then naming its commitment by id. A thread left citing
    nothing is dropped: it can no longer be checked."""
    shown = said | earlier.lines
    for item in [*notes.commitments, *notes.follow_ups, *notes.positions]:
        item.lines = [n for n in item.lines if n in said]
    for both in notes.contradictions:
        both.lines = [n for n in both.lines if n in said]
        both.against = [n for n in both.against if n in shown]
    notes.commitments = [c for c in notes.commitments if c.lines]
    notes.positions = [p for p in notes.positions if p.lines]
    shown_commitments = dict(enumerate(earlier.commitments, 1))
    for follow in notes.follow_ups:
        follow.commitment = shown_commitments.get(follow.commitment or 0)
    notes.follow_ups = [f for f in notes.follow_ups if f.lines and f.commitment]
    notes.contradictions = [c for c in notes.contradictions if c.lines and c.against]
    return notes
