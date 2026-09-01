"""Storing paper and finding it again.

Ingest is idempotent by construction: the storage key is derived from
the payload's SHA-256, so re-uploading a scan returns the document that
already exists rather than a second row. That is the property the whole
service is built around - a scanner that runs twice, an email fetched
again, a user who clicks upload twice all cost one document.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.storage import content_key, get_storage
from app.services.documents.models import DOCUMENT_KINDS, Document, DocumentTag


def _utcnow() -> datetime:
    """Naive UTC, the timestamp convention every service here shares.

    A local-time timestamp reads differently depending on where the
    process runs, which makes "received on the 27th" a question about
    the server rather than about the document.
    """
    return datetime.now(UTC).replace(tzinfo=None)


# The columns a client may change after the fact. Storage, hash, size and
# provenance describe the bytes and are fixed by them.
_EDITABLE = frozenset({"title", "kind", "document_date", "note"})


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
    ) -> Document:
        """Store bytes and record the document, or return the one that
        already holds these exact bytes.

        Deduped per owner rather than globally: two people holding the
        same form is two documents, and one person scanning it twice is
        one.
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
            return existing

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
            received_at=_utcnow(),
            source=source,
            note=note,
        )
        self.db.add(document)
        await self.db.flush()
        return document

    async def by_content(
        self, key: str, *, owner_user_id: int | None = None
    ) -> Document | None:
        """The live document holding these bytes, if there is one."""
        digest = key.rsplit("/", 1)[-1]
        query = select(Document).where(
            Document.content_hash == digest, Document.deleted_at.is_(None)
        )
        if owner_user_id is not None:
            query = query.where(Document.owner_user_id == owner_user_id)
        return (await self.db.exec(query)).first()

    async def get(
        self, document_id: int, *, owner_user_id: int | None = None
    ) -> Document | None:
        query = select(Document).where(
            Document.id == document_id, Document.deleted_at.is_(None)
        )
        if owner_user_id is not None:
            query = query.where(Document.owner_user_id == owner_user_id)
        return (await self.db.exec(query)).first()

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
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Document], int]:
        """A page of live documents, newest first, plus the total."""
        query = select(Document).where(Document.deleted_at.is_(None))
        count_query = (
            select(func.count())
            .select_from(Document)
            .where(Document.deleted_at.is_(None))
        )
        if owner_user_id is not None:
            query = query.where(Document.owner_user_id == owner_user_id)
            count_query = count_query.where(Document.owner_user_id == owner_user_id)
        if kind is not None:
            query = query.where(Document.kind == kind)
            count_query = count_query.where(Document.kind == kind)
        if tag is not None:
            tagged = select(DocumentTag.document_id).where(DocumentTag.label == tag)
            query = query.where(Document.id.in_(tagged))
            count_query = count_query.where(Document.id.in_(tagged))
        total = (await self.db.exec(count_query)).one()
        rows = (
            await self.db.exec(
                query.order_by(Document.created_at.desc(), Document.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), int(total)

    async def update(
        self,
        document_id: int,
        fields: dict[str, Any],
        *,
        owner_user_id: int | None = None,
    ) -> Document | None:
        """Change what the paper is called, what it is, when it is dated,
        or the note on it. Only the keys present change; a key set to
        None clears that field."""
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
        document = await self.get(document_id, owner_user_id=owner_user_id)
        if document is None:
            return None
        for name, value in fields.items():
            setattr(document, name, value.strip() if name == "title" else value)
        document.updated_at = _utcnow()
        self.db.add(document)
        await self.db.flush()
        return document

    async def summary(self, *, owner_user_id: int | None = None) -> dict[str, Any]:
        """What the card shows: how much paper, how recent, how heavy."""
        live = Document.deleted_at.is_(None)
        if owner_user_id is not None:
            live = live & (Document.owner_user_id == owner_user_id)
        by_kind = (
            await self.db.exec(
                select(
                    Document.kind,
                    func.count(),
                    func.coalesce(func.sum(Document.byte_size), 0),
                )
                .where(live)
                .group_by(Document.kind)
            )
        ).all()
        month_start = _utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        this_month = (
            await self.db.exec(
                select(func.count())
                .select_from(Document)
                .where(live, Document.received_at >= month_start)
            )
        ).one()
        return {
            "total": sum(int(n) for _, n, _ in by_kind),
            "this_month": int(this_month),
            "bytes": sum(int(b) for _, _, b in by_kind),
            "by_kind": {kind: int(n) for kind, n, _ in by_kind},
        }

    async def tag_counts(
        self, *, owner_user_id: int | None = None
    ) -> list[tuple[str, int]]:
        """Every label in use on live documents, most used first."""
        query = (
            select(DocumentTag.label, func.count())
            .join(Document, Document.id == DocumentTag.document_id)
            .where(Document.deleted_at.is_(None))
        )
        if owner_user_id is not None:
            query = query.where(Document.owner_user_id == owner_user_id)
        rows = (
            await self.db.exec(
                query.group_by(DocumentTag.label).order_by(
                    func.count().desc(), DocumentTag.label
                )
            )
        ).all()
        return [(str(label), int(n)) for label, n in rows]

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
        """Tags for a page of documents in ONE query.

        A per-row lookup is the N+1 the house rules forbid, and a listing
        endpoint is exactly where it bites.
        """
        if not document_ids:
            return {}
        rows = (
            await self.db.exec(
                select(DocumentTag)
                .where(DocumentTag.document_id.in_(document_ids))
                .order_by(DocumentTag.document_id, DocumentTag.label)
            )
        ).all()
        grouped: dict[int, list[str]] = {}
        for row in rows:
            grouped.setdefault(row.document_id, []).append(row.label)
        return grouped

    async def tags_for(self, document_id: int) -> list[str]:
        rows = (
            await self.db.exec(
                select(DocumentTag)
                .where(DocumentTag.document_id == document_id)
                .order_by(DocumentTag.label)
            )
        ).all()
        return [row.label for row in rows]

    async def soft_delete(
        self, document_id: int, *, owner_user_id: int | None = None
    ) -> bool:
        """Retire a document without touching storage.

        The bytes stay: another document may hold the same content hash,
        and an audit trail that loses its subject is not an audit trail.
        """
        document = await self.get(document_id, owner_user_id=owner_user_id)
        if document is None:
            return False
        document.deleted_at = _utcnow()
        self.db.add(document)
        await self.db.flush()
        return True
