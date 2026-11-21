"""A file of mail becomes rows, and its paper becomes documents.

Short holds on the database, never one long one: the batch; then the
messages, a chunk per transaction; then the counts. The parse happens
before the first and the extraction dispatch after the last, holding
nothing - a file of ten thousand messages is slow, and SQLite's single
writer must not wait on it.

THE SEAM: who a sender is belongs to whatever consumes the messages, not
to the import. A contacts service plugs in here, with
``register_messages_filed``: after a batch's messages are filed, each hook
is handed the batch's NEW ``MailMessage`` rows (``from_address`` is the
sender to match) in a session of its own. The template registers nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import hashlib

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import OpenSession
from app.core.discovery import import_modules_named
from app.core.log import logger
from app.core.time import utcnow
from app.services.documents.domains.extraction.dispatch import read_quietly
from app.services.documents.models import DocumentPage
from app.services.documents.service import DocumentService
from app.services.mail import parse, queries
from app.services.mail.models import (
    SOURCE_FILE,
    MailAttachment,
    MailBatch,
    MailMessage,
)
from app.services.system.jobs import Report

# A consumer of what a batch filed: (its session, the new messages, the
# owner). Stage writes on the session; it commits when the hook returns.
MessagesFiled = Callable[[AsyncSession, list[MailMessage], int | None], Awaitable[None]]
_filed_hooks: list[MessagesFiled] = []


def register_messages_filed(hook: MessagesFiled) -> None:
    """Hand every batch's new messages to ``hook``, after they are filed.

    Call it from your service's ``mail_hooks.py``: ingest imports every
    such module before it tells anyone, so the hook is there in each
    process that files mail, the worker's included.

    Each hook runs in its own session, in registration order. One that
    raises is rolled back and logged, never the import's failure: the
    messages are filed by then. A message is new once, so a hook sees it
    once however often the file is read again.
    """
    _filed_hooks.append(hook)


# A heartbeat per this many messages. Each may carry paper to hash and
# store, so the cadence is short.
PROGRESS_EVERY = 200
# Messages per transaction. A commit is an fsync; one per message on a
# 3,000-message export is 3,000 fsyncs for no isolation anybody wanted - a
# message is idempotent on its Message-ID, so a re-run after a crash
# mid-chunk files the rest and skips what landed. The lock is held for
# one chunk's milliseconds, never across the file.
COMMIT_EVERY = 100


@dataclass
class MailImportResult:
    batch_id: int
    messages_total: int = 0
    messages_new: int = 0
    messages_duplicate: int = 0
    letters_filed: int = 0
    attachments_filed: int = 0
    attachments_duplicate: int = 0
    # Paper that was NEW to documents, and so gets read.
    document_ids: list[int] = field(default_factory=list)

    def as_payload(self) -> dict[str, int]:
        return {
            "batch_id": self.batch_id,
            "messages_total": self.messages_total,
            "messages_new": self.messages_new,
            "messages_duplicate": self.messages_duplicate,
            "letters_filed": self.letters_filed,
            "attachments_filed": self.attachments_filed,
            "attachments_duplicate": self.attachments_duplicate,
        }


def _unheard(label: str) -> None:
    """Where progress goes when nobody is watching."""


async def ingest_mail(
    open_session: OpenSession,
    *,
    data: bytes,
    file_name: str,
    owner_user_id: int | None = None,
    report: Report = _unheard,
) -> MailImportResult:
    """Read a mailbox export into documents. Returns what it did.

    Idempotent twice over: the same bytes are answered with the batch
    that already read them, and a message already filed - by Message-ID,
    whatever file it came in - is counted and left alone.
    """
    # Refuses a file that is not mail before anything is written.
    messages = parse.messages(data, file_name)
    return await ingest_messages(
        open_session,
        messages,
        file_name=file_name,
        sha=hashlib.sha256(data).hexdigest(),
        owner_user_id=owner_user_id,
        report=report,
    )


async def ingest_messages(
    open_session: OpenSession,
    messages: list[parse.ParsedMessage],
    *,
    file_name: str,
    sha: str,
    source: str = SOURCE_FILE,
    owner_user_id: int | None = None,
    report: Report = _unheard,
) -> MailImportResult:
    """Messages already parsed - from a file or a mailbox pull - into
    documents. ``file_name`` is what the batch is called (the file, or the
    mailbox); ``sha`` is over the bytes they came from, so the same bytes
    are answered with the batch that already read them - unless that run
    stopped, when the same batch is picked back up (what it filed counts
    as already filed)."""
    async with open_session() as db:
        batch = await queries.mail_batch_by_sha(db, sha)
        if batch is not None and batch.status != "failed":
            logger.info(
                "mail.import.identical_reupload",
                file_name=file_name,
                batch_id=batch.id,
            )
            return _result_of(batch)
        if batch is None:
            batch = MailBatch(
                owner_user_id=owner_user_id,
                file_name=file_name,
                file_sha256=sha,
                source=source,
                messages_total=len(messages),
            )
        batch.status, batch.error = "processing", None
        db.add(batch)
        await db.flush()
        batch_id = int(batch.id or 0)

    try:
        result, filed = await _file_all(
            open_session, messages, batch_id, owner_user_id, report
        )
    except Exception as exc:
        async with open_session() as db:
            await queries.mark_batch_failed(
                db, batch_id, f"The import stopped partway ({type(exc).__name__})."
            )
        raise

    await _tell_filed(open_session, filed, owner_user_id)
    # Holding nothing: each read is a job of its own on the worker.
    for document_id in result.document_ids:
        await read_quietly(document_id, owner_user_id=owner_user_id)

    logger.info("mail.import.finished", file_name=file_name, **result.as_payload())
    return result


async def _file_all(
    open_session: OpenSession,
    messages: list[parse.ParsedMessage],
    batch_id: int,
    owner_user_id: int | None,
    report: Report,
) -> tuple[MailImportResult, list[MailMessage]]:
    """The messages filed in chunks, then the batch's counts written."""

    report(f"Reading {len(messages):,} messages...")
    result = MailImportResult(batch_id=batch_id, messages_total=len(messages))
    filed: list[MailMessage] = []

    for start in range(0, len(messages), COMMIT_EVERY):
        chunk = messages[start : start + COMMIT_EVERY]
        async with open_session() as db:
            seen = await queries.filed_message_ids(db, [m.message_id for m in chunk])
            for message in chunk:
                if message.message_id in seen:
                    result.messages_duplicate += 1
                    continue
                # The same message twice in one file is one message too.
                seen.add(message.message_id)
                filed.append(
                    await _file_one(db, message, result, owner_user_id=owner_user_id)
                )
        done = start + len(chunk)
        if done % PROGRESS_EVERY == 0 or done == len(messages):
            report(
                f"Read {done:,} of {len(messages):,} messages - "
                f"{result.attachments_filed:,} attachments filed"
            )

    async with open_session() as db:
        batch = await db.get(MailBatch, batch_id)
        assert batch is not None
        batch.messages_new = result.messages_new
        batch.messages_duplicate = result.messages_duplicate
        batch.letters_filed = result.letters_filed
        batch.attachments_filed = result.attachments_filed
        batch.attachments_duplicate = result.attachments_duplicate
        batch.status = "done"
        batch.finished_at = utcnow()
        db.add(batch)
        await db.flush()
    return result, filed


async def _tell_filed(
    open_session: OpenSession, rows: list[MailMessage], owner_user_id: int | None
) -> None:
    """The seam: each registered hook, given the batch's new messages."""
    if not rows:
        return
    import app.services as services

    # Found on disk, as tools and change types are; importing twice is a
    # no-op.
    import_modules_named(services, "mail_hooks")
    for hook in _filed_hooks:
        try:
            async with open_session() as db:
                await hook(db, rows, owner_user_id)
        except Exception:
            logger.exception("mail.import.hook_failed", hook=hook.__qualname__)


async def _file_one(
    db: AsyncSession,
    message: parse.ParsedMessage,
    result: MailImportResult,
    *,
    owner_user_id: int | None,
) -> MailMessage:
    """One new message: the row, its letter, and its paper."""
    row = MailMessage(
        owner_user_id=owner_user_id,
        batch_id=result.batch_id,
        message_id=message.message_id,
        from_address=message.from_address,
        from_name=message.from_name or None,
        subject=message.subject or None,
        sent_at=message.sent_at,
    )
    db.add(row)
    await db.flush()
    result.messages_new += 1

    documents = DocumentService(db)
    # The letter's own date, not the day it was imported.
    dated = message.sent_at.date() if message.sent_at else None
    # The message as a letter: much of what arrives has no attachment, and
    # the body is the letter. Its page is written as already read - the
    # mail IS text - so there is nothing to hand a reader.
    letter = letter_text(message)
    if letter:
        paper, created = await documents.store(
            letter.encode("utf-8"),
            title=message.subject or "(no subject)",
            kind="letter",
            media_type="text/plain",
            owner_user_id=owner_user_id,
            document_date=dated,
            source="mail",
            channel="email",
            page_count=1,
        )
        if created:
            db.add(
                DocumentPage(
                    document_id=int(paper.id or 0),
                    page_number=1,
                    status="read",
                    method="mail",
                    text=letter,
                )
            )
            result.letters_filed += 1
        row.document_id = paper.id
        db.add(row)

    linked: set[int] = set()
    for attachment in message.attachments:
        if not attachment.data:
            continue
        paper, created = await documents.store(
            attachment.data,
            title=attachment.filename,
            media_type=attachment.media_type,
            owner_user_id=owner_user_id,
            document_date=dated,
            source="mail",
            channel="email",
        )
        paper_id = int(paper.id or 0)
        if created:
            result.attachments_filed += 1
            result.document_ids.append(paper_id)
        else:
            result.attachments_duplicate += 1
        # The same file attached twice to one message is one link.
        if paper_id in linked:
            continue
        linked.add(paper_id)
        db.add(
            MailAttachment(
                message_id=int(row.id or 0),
                document_id=paper_id,
                filename=attachment.filename,
            )
        )
    await db.flush()
    return row


def _result_of(batch: MailBatch) -> MailImportResult:
    return MailImportResult(
        batch_id=int(batch.id or 0),
        messages_total=batch.messages_total,
        messages_new=0,
        messages_duplicate=batch.messages_total,
        attachments_filed=0,
        attachments_duplicate=batch.attachments_filed + batch.attachments_duplicate,
    )


def letter_text(message: parse.ParsedMessage) -> str:
    """The message as a page of text, or "" when the body said nothing.

    The header is the letterhead. A printed letter carries the sender at
    the top; this puts the From, Subject and Date on the first lines for
    the same reason, so whatever reads a page for who sent it reads this
    one the same way.
    """
    body = (message.body_text or "").strip()
    if not body:
        return ""
    who = (
        f"{message.from_name} <{message.from_address}>"
        if message.from_name
        else message.from_address
    )
    head = [f"From: {who}", f"Subject: {message.subject}"]
    if message.sent_at:
        head.append(f"Date: {message.sent_at.date().isoformat()}")
    return "\n".join([*head, "", body])
