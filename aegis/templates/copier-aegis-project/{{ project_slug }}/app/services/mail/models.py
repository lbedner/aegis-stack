"""A file of mail, the messages in it, the paper each one carried, and
the mailbox the app pulls."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# How a batch's messages got here: a file somebody dropped, or a pull
# from a mailbox the app reads itself (``pull``).
SOURCE_FILE, SOURCE_IMAP = "file", "imap"


class MailBatch(SQLModel, table=True):
    """One file (or one pull), and what reading it did.

    The reversible unit, its counts, and ``file_sha256`` so an identical
    re-upload is answered with the batch that already read it rather than
    read again.
    """

    __tablename__ = "mail_batch"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'done', 'failed')", name="ck_mail_batch_status"
        ),
        CheckConstraint("source IN ('file', 'imap')", name="ck_mail_batch_source"),
        # Same bytes, same batch. NOT per owner: owner_user_id is NULL where
        # nobody signs in, and SQLite treats every NULL as distinct in a
        # unique index, so ``(owner, sha)`` would never collide.
        Index("uq_mail_batch_file", "file_sha256", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    # The file's name, or the mailbox's label when pulled.
    file_name: str = Field(max_length=255)
    file_sha256: str = Field(max_length=64)
    source: str = Field(default=SOURCE_FILE, max_length=16)
    messages_total: int = Field(default=0)
    messages_new: int = Field(default=0)
    messages_duplicate: int = Field(default=0)
    letters_filed: int = Field(default=0)
    attachments_filed: int = Field(default=0)
    attachments_duplicate: int = Field(default=0)
    status: str = Field(default="processing", max_length=16)
    error: str | None = Field(default=None, max_length=512)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)


class MailMessage(SQLModel, table=True):
    """One message, once: who sent it, when, what it was about, and the
    letter its body became. ``from_address`` is what a consumer matches
    a sender on (``ingest.register_messages_filed``)."""

    __tablename__ = "mail_message"
    __table_args__ = (
        # RFC 5322: unique per message. THE dedup key; a re-export of an
        # overlapping range lands each message once, whatever the file. On
        # message_id alone, for the same reason as the batch's sha.
        Index("uq_mail_message_id", "message_id", unique=True),
        Index("ix_mail_message_batch", "batch_id"),
        Index("ix_mail_message_sent", "sent_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    batch_id: int = Field(foreign_key="mail_batch.id")
    message_id: str = Field(max_length=998)
    from_address: str = Field(max_length=320)
    from_name: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=998)
    sent_at: datetime | None = Field(default=None)
    # The message as a LETTER: its body as page 1, already read. Null when
    # the body said nothing.
    document_id: int | None = Field(default=None, foreign_key="document.id")
    created_at: datetime = Field(default_factory=utcnow)


class MailAttachment(SQLModel, table=True):
    """A message's paper, as it was filed.

    A link rather than a column on ``document``: the same statement can
    arrive on two messages, and documents hold it once.
    """

    __tablename__ = "mail_attachment"
    __table_args__ = (
        Index("uq_mail_attachment", "message_id", "document_id", unique=True),
        Index("ix_mail_attachment_document", "document_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="mail_message.id")
    document_id: int = Field(foreign_key="document.id")
    # What it was called on the message.
    filename: str = Field(max_length=255)


class MailMailbox(SQLModel, table=True):
    """A mailbox the app pulls, and where the pull got to.

    The watermark IMAP gives: UIDs climb within one UIDVALIDITY, so the
    next pull asks for everything above the last one seen, and starts
    over when the server renumbers. What went wrong last time sits here,
    once, for the Mail page: a wrong password is a line a person reads,
    not a log line nobody does.
    """

    __tablename__ = "mail_mailbox"
    __table_args__ = (Index("uq_mail_mailbox_key", "key", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    # host/user/folder: one row per mailbox the secrets name.
    key: str = Field(max_length=640)
    uidvalidity: int | None = Field(default=None)
    uid_last: int = Field(default=0)
    last_pulled_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=255)
