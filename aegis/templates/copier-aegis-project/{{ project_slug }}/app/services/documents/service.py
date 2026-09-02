"""Storing paper and finding it again.

Ingest is idempotent by construction: the storage key is derived from
the payload's SHA-256, so re-uploading a scan returns the document that
already exists rather than a second row. That is the property the whole
service is built around - a scanner that runs twice, an email fetched
again, a user who clicks upload twice all cost one document.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import content_key, get_storage
from app.services.documents import queries
from app.services.documents.models import DOCUMENT_KINDS, Document, DocumentTag, utcnow

# The columns a client may change after the fact. Storage, hash, size and
# provenance describe the bytes and are fixed by them.
_EDITABLE = frozenset(
    {"title", "kind", "document_date", "note", "channel", "supersedes_id", "protected"}
)


class ProtectedDocumentError(PermissionError):
    """Retiring a protected document needs its title typed back."""


class DocumentService:
    """The document store's whole surface."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ingest(
        self,
        data: bytes,
        *,
        title: str,
        kind: str = "other",
        media_type: str | None = None,
        owner_user_id: int | None = None,
        document_date: date | None = None,
        source: str = "upload",
        note: str | None = None,
        page_count: int | None = None,
        channel: str | None = None,
    ) -> Document:
        """Store bytes and record the document, or return the one that
        already holds these exact bytes. See ``store`` for the version
        that also says which of the two happened."""
        document, _ = await self.store(
            data,
            title=title,
            kind=kind,
            media_type=media_type,
            owner_user_id=owner_user_id,
            document_date=document_date,
            source=source,
            note=note,
            page_count=page_count,
            channel=channel,
        )
        return document

    async def store(
        self,
        data: bytes,
        *,
        title: str,
        kind: str = "other",
        media_type: str | None = None,
        owner_user_id: int | None = None,
        document_date: date | None = None,
        source: str = "upload",
        note: str | None = None,
        page_count: int | None = None,
        channel: str | None = None,
    ) -> tuple[Document, bool]:
        """Store bytes and record the document, or return the one that
        already holds these exact bytes, plus whether a row was created.

        Deduped per owner rather than globally: two people holding the
        same form is two documents, and one person scanning it twice is
        one. The flag comes from the single dedupe lookup here, so a
        caller never has to repeat it to learn the outcome.
        """
        if not data:
            raise ValueError("A document needs content.")
        display = (title or "").strip()
        if not display:
            raise ValueError("A document needs a title.")
        if kind not in DOCUMENT_KINDS:
            raise ValueError(
                f"Unknown document kind {kind!r}; expected one of "
                f"{', '.join(DOCUMENT_KINDS)}."
            )

        key = content_key(data)
        existing = await self.by_content(key, owner_user_id=owner_user_id)
        if existing is not None:
            return existing, False

        storage = get_storage()
        stored_key = await storage.put(data, content_type=media_type)
        document = Document(
            owner_user_id=owner_user_id,
            title=display,
            kind=kind,
            storage_key=stored_key,
            storage_backend=storage.backend_name,
            content_hash=stored_key.rsplit("/", 1)[-1],
            media_type=media_type,
            byte_size=len(data),
            page_count=page_count,
            document_date=document_date,
            received_at=utcnow(),
            source=source,
            note=note,
            channel=channel,
        )
        self.db.add(document)
        await self.db.flush()
        return document, True

    async def by_content(
        self, key: str, *, owner_user_id: int | None = None
    ) -> Document | None:
        """The live document holding these bytes, if there is one."""
        return await queries.document_by_content(
            self.db, key, owner_user_id=owner_user_id
        )

    async def get(
        self, document_id: int, *, owner_user_id: int | None = None
    ) -> Document | None:
        return await queries.document_by_id(
            self.db, document_id, owner_user_id=owner_user_id
        )

    async def content(
        self, document_id: int, *, owner_user_id: int | None = None
    ) -> bytes | None:
        """The stored bytes, read through the storage backend the row
        names rather than a path this service constructs."""
        document = await self.get(document_id, owner_user_id=owner_user_id)
        if document is None:
            return None
        return await get_storage().get(document.storage_key)

    async def list_documents(
        self,
        *,
        owner_user_id: int | None = None,
        kind: str | None = None,
        tag: str | None = None,
        channel: str | None = None,
        include_superseded: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Document], int]:
        """A page of live documents, newest first, plus the total. Heads of
        version chains only unless ``include_superseded``."""
        return await queries.documents_page(
            self.db,
            owner_user_id=owner_user_id,
            kind=kind,
            tag=tag,
            channel=channel,
            include_superseded=include_superseded,
            page=page,
            page_size=page_size,
        )

    async def update(
        self,
        document_id: int,
        fields: dict[str, Any],
        *,
        owner_user_id: int | None = None,
    ) -> Document | None:
        """Change what the paper is called, what it is, when it is dated,
        or the note on it. Only the keys present change. ``document_date``
        and ``note`` clear when set to None; ``title`` and ``kind`` must
        always hold a value, so None there is refused."""
        unknown = set(fields) - _EDITABLE
        if unknown:
            raise ValueError(f"Cannot change {', '.join(sorted(unknown))}.")
        if "kind" in fields and fields["kind"] not in DOCUMENT_KINDS:
            raise ValueError(
                f"Unknown document kind {fields['kind']!r}; expected one of "
                f"{', '.join(DOCUMENT_KINDS)}."
            )
        if "title" in fields and not (fields["title"] or "").strip():
            raise ValueError("A document needs a title.")
        if "protected" in fields and not isinstance(fields["protected"], bool):
            raise ValueError("protected must be true or false.")
        document = await self.get(document_id, owner_user_id=owner_user_id)
        if document is None:
            return None
        if fields.get("supersedes_id") is not None:
            await self._check_supersedes(
                document_id, int(fields["supersedes_id"]), owner_user_id=owner_user_id
            )
        for name, value in fields.items():
            setattr(document, name, value.strip() if name == "title" else value)
        document.updated_at = utcnow()
        self.db.add(document)
        await self.db.flush()
        return document

    async def _check_supersedes(
        self, document_id: int, target_id: int, *, owner_user_id: int | None
    ) -> None:
        """The target must exist, be someone else's version, and not
        already descend from this document, or the chain would loop."""
        if target_id == document_id:
            raise ValueError("A document cannot replace itself.")
        target = await self.get(target_id, owner_user_id=owner_user_id)
        if target is None:
            raise ValueError("Unknown document to replace.")
        seen: set[int] = set()
        while target is not None and target.supersedes_id is not None:
            if target.supersedes_id == document_id or target.id in seen:
                raise ValueError("That would make the version chain loop.")
            seen.add(target.id or 0)
            target = await self.get(target.supersedes_id, owner_user_id=owner_user_id)

    async def summary(self, *, owner_user_id: int | None = None) -> dict[str, Any]:
        """What the card shows: how much paper, how recent, how heavy."""
        return await queries.store_summary(self.db, owner_user_id=owner_user_id)

    async def tag_counts(
        self, *, owner_user_id: int | None = None
    ) -> list[tuple[str, int]]:
        """Every label in use on live documents, most used first."""
        return await queries.tag_counts(self.db, owner_user_id=owner_user_id)

    async def untag(self, document_id: int, label: str) -> bool:
        """Take a label off; False when it was not there."""
        row = (
            await self.db.exec(
                select(DocumentTag).where(
                    DocumentTag.document_id == document_id,
                    DocumentTag.label == label,
                )
            )
        ).first()
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def tag(self, document_id: int, label: str) -> DocumentTag | None:
        """Label a document; re-tagging with the same label is a no-op."""
        clean = (label or "").strip()
        if not clean:
            raise ValueError("A tag needs a label.")
        document = await self.get(document_id)
        if document is None:
            return None
        existing = (
            await self.db.exec(
                select(DocumentTag).where(
                    DocumentTag.document_id == document_id,
                    DocumentTag.label == clean,
                )
            )
        ).first()
        if existing is not None:
            return existing
        row = DocumentTag(document_id=document_id, label=clean)
        self.db.add(row)
        await self.db.flush()
        return row

    async def tags_for_many(self, document_ids: list[int]) -> dict[int, list[str]]:
        """Tags for a page of documents in one query, never one per row."""
        return await queries.tags_for_many(self.db, document_ids)

    async def tags_for(self, document_id: int) -> list[str]:
        return await queries.tags_for(self.db, document_id)

    async def soft_delete(
        self,
        document_id: int,
        *,
        owner_user_id: int | None = None,
        confirm: str | None = None,
    ) -> bool:
        """Retire a document without touching storage.

        The bytes stay: another document may hold the same content hash,
        and an audit trail that loses its subject is not an audit trail.
        A protected document goes only when ``confirm`` is its exact title.
        """
        document = await self.get(document_id, owner_user_id=owner_user_id)
        if document is None:
            return False
        if document.protected and confirm != document.title:
            raise ProtectedDocumentError(
                "This document is protected; confirm by sending its exact title."
            )
        document.deleted_at = utcnow()
        self.db.add(document)
        await self.db.flush()
        return True
