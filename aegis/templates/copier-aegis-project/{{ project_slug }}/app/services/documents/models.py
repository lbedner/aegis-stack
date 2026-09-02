"""The document row: where the paper is, and what it is.

Bytes live in object storage under a key derived from their own SHA-256
(see ``app.core.storage``), so this table never holds a path and the same
scan uploaded twice is one row pointing at one object.

What a document MEANS - the case it belongs to, the deadline it creates,
the claim it proves - is deliberately absent. That is the consuming
application's business; this service stores paper and finds it again.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, Index
from sqlmodel import Field, SQLModel

# What kind of paper this is. Coarse on purpose: a fixed taxonomy would
# be the framework deciding what documents exist, which it should not.
# Anything finer rides tags.
DOCUMENT_KINDS = (
    "letter",
    "statement",
    "form",
    "identification",
    "receipt",
    "other",
)


def utcnow() -> datetime:
    """Naive UTC, matching the timestamp columns across services.

    A local-time timestamp reads differently depending on where the
    process runs, which makes "received on the 27th" a question about
    the server rather than about the document.
    """
    from datetime import UTC

    return datetime.now(UTC).replace(tzinfo=None)


class Document(SQLModel, table=True):
    """One stored document."""

    __tablename__ = "document"
    __table_args__ = (
        Index("ix_document_owner", "owner_user_id"),
        # The dedupe rule, enforced rather than merely checked: ingest
        # reads before it writes, and two concurrent uploads of the same
        # bytes can both miss that read. Partial, so a retired document
        # does not block re-filing the same paper later - the same shape
        # the soft-delete uniques elsewhere use.
        Index(
            "ix_document_owner_hash",
            "owner_user_id",
            "content_hash",
            unique=True,
            sqlite_where=Column("deleted_at").is_(None),
            postgresql_where=Column("deleted_at").is_(None),
        ),
        Index("ix_document_kind", "kind"),
        Index("ix_document_supersedes", "supersedes_id"),
        CheckConstraint(
            "kind IN ('letter', 'statement', 'form', 'identification', "
            "'receipt', 'other')",
            name="ck_document_kind",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    owner_user_id: int | None = Field(default=None)
    title: str = Field(max_length=255)
    kind: str = Field(default="other", max_length=32)
    # Where the bytes are. The key is content-derived, so it is portable
    # across backends; the backend name is recorded so a half-migrated
    # store still resolves every row.
    storage_key: str = Field(max_length=128)
    storage_backend: str = Field(default="filesystem", max_length=32)
    content_hash: str = Field(max_length=64)
    media_type: str | None = Field(default=None, max_length=128)
    byte_size: int = Field(default=0)
    page_count: int | None = None
    # When the DOCUMENT is dated (the letter's own date), as opposed to
    # when it arrived - a renewal request dated the 27th can land in
    # August's post.
    document_date: date | None = None
    received_at: datetime | None = None
    source: str = Field(default="upload", max_length=32)
    # How the paper reached you (mail, download, scan, email), as opposed
    # to ``source``, which is the mechanism that stored the bytes.
    channel: str | None = Field(default=None, max_length=32)
    # A newer version points at the one it replaces. The head of a chain
    # is the copy to cite; the rest stay reachable beneath it. Supersede,
    # never overwrite: the same rule facts follow.
    supersedes_id: int | None = Field(default=None, foreign_key="document.id")
    # One more gate on delete, and never auto-purged. Not an access tier.
    protected: bool = Field(default=False)
    note: str | None = None
    meta_data: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("meta_data", JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def __repr__(self) -> str:
        return f"<Document id={self.id} title={self.title!r} kind={self.kind}>"


class DocumentTag(SQLModel, table=True):
    """A free-form label on a document.

    Tags rather than a taxonomy: what counts as a meaningful category
    differs per application, and the framework has no business guessing.
    """

    __tablename__ = "document_tag"
    __table_args__ = (
        Index("ix_document_tag_document", "document_id"),
        Index("uq_document_tag", "document_id", "label", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id")
    label: str = Field(max_length=64)


class DocumentPage(SQLModel, table=True):
    """One page of a document as extraction read it.

    ``method`` says how the text was obtained (the PDF's own text layer,
    a vision model over the rendered page, or none), so any claim built
    on it later can cite both the page and the way it was read. A page
    that could not be read is a row with ``status='unread'`` and the
    reason in ``detail``, never an absence.
    """

    __tablename__ = "document_page"
    __table_args__ = (
        Index("ix_document_page_document", "document_id"),
        Index("uq_document_page", "document_id", "page_number", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="document.id")
    page_number: int
    status: str = Field(default="unread", max_length=16)
    method: str = Field(default="none", max_length=16)
    text: str | None = None
    # The rendered page in object storage, what the thumbnail strip shows.
    image_key: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    detail: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None
