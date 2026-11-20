"""The mail service's reads and its small writes: the batch a file was
already read by, which messages are already filed, and the mailbox rows
a pull keeps its place in."""

from __future__ import annotations

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.mail.models import (
    MailAttachment,
    MailBatch,
    MailMailbox,
    MailMessage,
)


async def mail_batch_by_sha(db: AsyncSession, sha: str) -> MailBatch | None:
    """The batch that already read a file with these exact bytes."""
    return (
        await db.exec(select(MailBatch).where(MailBatch.file_sha256 == sha))
    ).first()


async def filed_message_ids(db: AsyncSession, message_ids: list[str]) -> set[str]:
    """Which of these Message-IDs are already filed, in one query."""
    rows = await db.exec(
        select(MailMessage.message_id).where(
            col(MailMessage.message_id).in_(message_ids)
        )
    )
    return set(rows.all())


async def messages_with_batches(
    db: AsyncSession, *, owner_user_id: int | None, limit: int
) -> list[tuple[MailMessage, MailBatch]]:
    """The newest messages first, each with the batch that brought it."""
    query = (
        select(MailMessage, MailBatch)
        .join(MailBatch, col(MailBatch.id) == col(MailMessage.batch_id))
        .where(MailMessage.owner_user_id == owner_user_id)
        .order_by(col(MailMessage.created_at).desc(), col(MailMessage.id).desc())
        .limit(limit)
    )
    return list((await db.exec(query)).all())


async def attachments_of(
    db: AsyncSession, message_ids: list[int]
) -> list[MailAttachment]:
    """Every attachment link of these messages, in one query."""
    rows = await db.exec(
        select(MailAttachment).where(col(MailAttachment.message_id).in_(message_ids))
    )
    return list(rows.all())


async def mailbox_state(db: AsyncSession, key: str) -> MailMailbox | None:
    """Where the pull of a mailbox got to, or nothing if never tried."""
    return (await db.exec(select(MailMailbox).where(MailMailbox.key == key))).first()


async def mailbox(db: AsyncSession, key: str) -> MailMailbox:
    """The row for a mailbox, made on first sight."""
    found = await mailbox_state(db, key)
    if found is None:
        found = MailMailbox(key=key)
        db.add(found)
        await db.flush()
    return found


async def mark_pulled(
    db: AsyncSession, mailbox_id: int, *, uidvalidity: int, uid_last: int
) -> None:
    """A pull that worked: the watermark it reached, and no error."""
    row = await db.get(MailMailbox, mailbox_id)
    assert row is not None
    row.uidvalidity, row.uid_last = uidvalidity, uid_last
    row.last_pulled_at, row.last_error = utcnow(), None
    db.add(row)
    await db.flush()


async def mark_batch_failed(db: AsyncSession, batch_id: int, error: str) -> None:
    """A run that stopped: the one line why, so the same bytes retry."""
    batch = await db.get(MailBatch, batch_id)
    assert batch is not None
    batch.status, batch.error, batch.finished_at = "failed", error, utcnow()
    db.add(batch)
    await db.flush()


async def mark_failed(db: AsyncSession, mailbox_id: int, error: str) -> None:
    """A pull that did not: the one line why. The watermark stays."""
    row = await db.get(MailMailbox, mailbox_id)
    assert row is not None
    row.last_error = error
    db.add(row)
    await db.flush()
