"""What an action is given: the moment and what led to it.

One excerpt for every action; each frames it its own way. The default
framing asks a coding agent, sitting in the repository of the system
being discussed, to answer from the code.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.meetings.domains.moments import queries as moments_queries
from app.services.meetings.models import Meeting, MeetingMoment, TranscriptLine

# How much of the call before the moment comes with it.
CONTEXT_LINES = 20


@dataclass(frozen=True)
class Excerpt:
    """A moment with what led to it: who said what, in order, the moment's
    own line last."""

    kind: str
    link: str
    speaker: str
    text: str
    before: list[tuple[str, str]]


async def excerpt(db: AsyncSession, moments: list[MeetingMoment]) -> Excerpt:
    """``moments`` (one, or a burst of them, in order) with the lines said
    up to them, read from the database: the call's last lines up to the
    card's last moment, or, for a card asked across the call, what led to
    its first moment and its moments' own lines."""
    meeting = await db.get_one(Meeting, moments[0].meeting_id)
    meeting_id = meeting.id or 0
    end = await db.get_one(TranscriptLine, moments[-1].line_id)
    said = await moments_queries.said(
        db, meeting_id, up_to=end.start_seconds, last=2 * CONTEXT_LINES + 1
    )
    if moments[0].line_id not in {line_id for _, line_id, _ in said}:
        start = await db.get_one(TranscriptLine, moments[0].line_id)
        lead = await moments_queries.said(
            db, meeting_id, up_to=start.start_seconds, last=CONTEXT_LINES + 1
        )
        own = {moment.line_id for moment in moments}
        lines = await moments_queries.said(db, meeting_id, line_ids=own)
        said = [line for line in lead if line[1] not in own] + lines
    return excerpt_from(said, moments, meeting.url)


Said = list[tuple[str, int, str]]


def excerpt_from(said: Said, moments: list[MeetingMoment], link: str) -> Excerpt:
    """``moments`` with the lines said up to them, from ``said`` (the call's
    lines so far as speaker, line id and text, in order): at most
    ``CONTEXT_LINES`` before the first. A card of several is the lines it
    covers (``covered``), a line per turn, under no one speaker."""
    first, lines = covered(said, moments)
    before = [(who, text) for who, _, text in said[:first][-CONTEXT_LINES:]]
    if len(moments) == 1:
        speaker = lines[0][0] if lines else ""
        return Excerpt(moments[0].kind, link, speaker, moments[0].text, before)
    return Excerpt(moments[0].kind, link, "", turns(lines), before)


def covered(said: Said, moments: list[MeetingMoment]) -> tuple[int, Said]:
    """Where a card (its moments, in order) starts in ``said``, and the
    lines it covers: from its first moment's to its last's, what was said
    between them too; or, past ``CONTEXT_LINES`` (a topic asked across the
    call, not a burst), its moments' own lines alone."""
    at = {line_id: i for i, (_, line_id, _) in enumerate(said)}
    first = at.get(moments[0].line_id, len(said))
    lines = said[first : at.get(moments[-1].line_id, first) + 1]
    if len(lines) > CONTEXT_LINES:
        own = {moment.line_id for moment in moments}
        lines = [line for line in lines if line[1] in own]
    return first, lines


def around(
    said: Said, line_id: int, either_side: int = CONTEXT_LINES // 2
) -> tuple[Said, tuple[str, int, str], Said] | None:
    """The line ``line_id`` of ``said`` (speaker, line id, text, in order),
    with up to ``either_side`` lines before it and after it; None for a line
    ``said`` does not hold."""
    at = next((n for n, (_, i, _) in enumerate(said) if i == line_id), None)
    if at is None:
        return None
    return (
        said[max(0, at - either_side) : at],
        said[at],
        said[at + 1 : at + 1 + either_side],
    )


def turns(lines: Iterable[tuple[str, int, str]]) -> str:
    """Lines as a framing quotes them, one per turn: ``Speaker: text``."""
    return "\n".join(f"{who}: {text}" for who, _, text in lines)


def said_before(heard: Excerpt) -> str:
    """What led to the moment, a line per turn, for a framing to quote."""
    return turns((who, 0, text) for who, text in heard.before) or "(nothing)"


def the_question(heard: Excerpt) -> str:
    """What was asked, and by whom when one person asked it."""
    who = f"Then {heard.speaker} asked" if heard.speaker else "Then this was asked"
    return f"{who}:\n\n{heard.text}"


def for_an_agent(heard: Excerpt) -> str:
    """The excerpt as a coding agent in the system's repository reads it."""
    return (
        f"In a meeting ({heard.link}), this was said:\n\n{said_before(heard)}\n\n"
        f"{the_question(heard)}\n\n"
        "Answer it from the code in this repository: briefly, naming the files "
        "and functions that show it, and saying so plainly when the code does "
        "not answer it. Do not change anything."
    )
