"""The rows: a batch, its messages, and the paper each one carried."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import FilesystemStorage
from app.services.documents.service import DocumentService
from app.services.mail.models import MailAttachment, MailBatch, MailMessage


async def _batch(db: AsyncSession) -> MailBatch:
    batch = MailBatch(owner_user_id=None, file_name="export.mbox", file_sha256="a" * 64)
    db.add(batch)
    await db.flush()
    return batch


def _message(batch: MailBatch, message_id: str) -> MailMessage:
    return MailMessage(
        batch_id=batch.id or 0,
        message_id=message_id,
        from_address="a@b.example",
        subject="x",
        sent_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


class TestAMessageIsFiledOnce:
    async def test_the_message_id_is_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        batch = await _batch(async_db_session)
        for _ in range(2):
            async_db_session.add(_message(batch, "<same@example.com>"))
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    async def test_a_batch_is_one_file_and_says_what_it_did(
        self, async_db_session: AsyncSession
    ) -> None:
        batch = await _batch(async_db_session)
        assert (batch.status, batch.source) == ("processing", "file")
        assert batch.messages_new == 0 and batch.attachments_filed == 0

    async def test_the_same_bytes_are_one_batch(
        self, async_db_session: AsyncSession
    ) -> None:
        """An identical re-upload short-circuits: same sha, same batch,
        nothing read again."""
        await _batch(async_db_session)
        async_db_session.add(
            MailBatch(owner_user_id=None, file_name="again.mbox", file_sha256="a" * 64)
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestAnAttachmentLinksAMessageToPaper:
    async def test_the_link_names_the_file_as_it_arrived(
        self, async_db_session: AsyncSession, files: FilesystemStorage
    ) -> None:
        batch = await _batch(async_db_session)
        mail = _message(batch, "<m@example.com>")
        async_db_session.add(mail)
        await async_db_session.flush()
        paper = await DocumentService(async_db_session).ingest(
            b"%PDF-1.4 statement", title="statement.pdf", source="mail"
        )
        link = MailAttachment(
            message_id=mail.id or 0, document_id=paper.id or 0, filename="statement.pdf"
        )
        async_db_session.add(link)
        await async_db_session.flush()
        assert link.id is not None
