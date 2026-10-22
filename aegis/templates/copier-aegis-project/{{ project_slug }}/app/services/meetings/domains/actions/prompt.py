"""What an action is given: the moment and what led to it.

One excerpt for every action; each frames it its own way. The default
framing asks a coding agent, sitting in the repository of the system
being discussed, to answer from the code.
"""

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


async def excerpt(db: AsyncSession, moment: MeetingMoment) -> Excerpt:
    """``moment`` with the lines said up to it, read from the database."""
    meeting = await db.get_one(Meeting, moment.meeting_id)
    line = await db.get_one(TranscriptLine, moment.line_id)
    said = await moments_queries.said(
        db, moment.meeting_id, up_to=line.start_seconds, last=CONTEXT_LINES + 1
    )
    return excerpt_from(said, moment, meeting.url)


def excerpt_from(
    said: list[tuple[str, int, str]], moment: MeetingMoment, link: str
) -> Excerpt:
    """``moment`` with the lines said up to it, from ``said`` (the call's
    lines so far as speaker, line id and text, in order): at most
    ``CONTEXT_LINES`` before its own."""
    ids = [line_id for _, line_id, _ in said]
    at = ids.index(moment.line_id) if moment.line_id in ids else len(said)
    speaker = said[at][0] if at < len(said) else ""
    before = [(who, text) for who, _, text in said[:at][-CONTEXT_LINES:]]
    return Excerpt(moment.kind, link, speaker, moment.text, before)


def said_before(heard: Excerpt) -> str:
    """What led to the moment, a line per turn (``Speaker: text``), for a
    framing to quote."""
    said = "\n".join(f"{speaker}: {text}" for speaker, text in heard.before)
    return said or "(nothing)"


def for_an_agent(heard: Excerpt) -> str:
    """The excerpt as a coding agent in the system's repository reads it."""
    return (
        f"In a meeting ({heard.link}), this was said:\n\n{said_before(heard)}\n\n"
        f"Then {heard.speaker} asked:\n\n{heard.text}\n\n"
        "Answer it from the code in this repository: briefly, naming the files "
        "and functions that show it, and saying so plainly when the code does "
        "not answer it. Do not change anything."
    )
