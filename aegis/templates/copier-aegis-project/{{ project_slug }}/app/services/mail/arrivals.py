"""What came in: one answer for the page and for the chat.

What is waiting is a queue's question; this says what ARRIVED and what
each message became - a letter, its attachments - and, when nothing,
why. "Nothing happened" with no reason is indistinguishable from a
broken import. One set of rows, read by the Mail page and by the
assistant's ``arrivals`` tool, so the two cannot disagree.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.figures import FIGURES
from app.core.formatting import counted
from app.services.mail import queries
from app.services.mail.models import (
    SOURCE_IMAP,
    MailBatch,
    MailMessage,
)


class Paper(BaseModel):
    model_config = FIGURES

    document_id: int
    filename: str


class Arrival(BaseModel):
    """One message and what it became."""

    model_config = FIGURES

    id: int
    received_at: datetime
    sent_at: datetime | None
    sender: str  # the display name, else the address
    address: str
    subject: str
    letter_id: int | None
    attachments: list[Paper]
    became: str  # one sentence a person can read
    via: str  # the file it was dropped in, or the mailbox it was pulled from


class Day(BaseModel):
    model_config = FIGURES

    date: date
    messages: list[Arrival] = Field(default_factory=list)


async def arrivals(
    db: AsyncSession, *, owner_user_id: int | None, limit: int = 500
) -> list[Day]:
    """Everything that came in, grouped by the day it arrived, newest
    first. Two queries for the whole listing, never one per row."""
    pairs = await queries.messages_with_batches(
        db, owner_user_id=owner_user_id, limit=limit
    )
    if not pairs:
        return []
    ids = [int(row.id or 0) for row, _ in pairs]
    papers: dict[int, list[Paper]] = {}
    for link in await queries.attachments_of(db, ids):
        papers.setdefault(link.message_id, []).append(
            Paper(document_id=link.document_id, filename=link.filename)
        )

    days: dict[date, Day] = {}
    for row, batch in pairs:
        arrival = _arrival(row, papers.get(int(row.id or 0), []), batch)
        days.setdefault(
            arrival.received_at.date(), Day(date=arrival.received_at.date())
        ).messages.append(arrival)
    return [days[d] for d in sorted(days, reverse=True)]


def _arrival(row: MailMessage, papers: list[Paper], batch: MailBatch) -> Arrival:
    return Arrival(
        id=int(row.id or 0),
        received_at=row.created_at,
        sent_at=row.sent_at,
        sender=row.from_name or row.from_address,
        address=row.from_address,
        subject=row.subject or "(no subject)",
        letter_id=row.document_id,
        attachments=papers,
        became=_became(row, papers),
        via=f"pulled from {batch.file_name}"
        if batch.source == SOURCE_IMAP
        else batch.file_name,
    )


def _became(row: MailMessage, papers: list[Paper]) -> str:
    """What the message turned into, said once. A message that produced
    nothing says why: with no reason it reads as a broken import."""
    if row.document_id is None and not papers:
        return "nothing: empty message, no attachments"
    parts = ["letter"] if row.document_id is not None else []
    if papers:
        parts.append(counted(len(papers), "attachment"))
    return " + ".join(parts)
