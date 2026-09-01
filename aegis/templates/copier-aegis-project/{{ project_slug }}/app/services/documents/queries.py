"""Reads for the document store: one document, a page of them, and the
labels and totals over them. Writes stay in ``service.py``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.documents.models import Document, DocumentTag, utcnow


async def document_by_content(
    db: AsyncSession, key: str, *, owner_user_id: int | None = None
) -> Document | None:
    """The live document holding these bytes, if there is one."""
    digest = key.rsplit("/", 1)[-1]
    query = select(Document).where(
        Document.content_hash == digest, Document.deleted_at.is_(None)
    )
    if owner_user_id is not None:
        query = query.where(Document.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def document_by_id(
    db: AsyncSession, document_id: int, *, owner_user_id: int | None = None
) -> Document | None:
    query = select(Document).where(
        Document.id == document_id, Document.deleted_at.is_(None)
    )
    if owner_user_id is not None:
        query = query.where(Document.owner_user_id == owner_user_id)
    return (await db.exec(query)).first()


async def documents_page(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
    kind: str | None = None,
    tag: str | None = None,
    channel: str | None = None,
    include_superseded: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Document], int]:
    """A page of live documents, newest first, plus the total.

    By default only the head of each version chain is listed: a
    document another live document supersedes is reachable through
    that one, not beside it.
    """
    query = select(Document).where(Document.deleted_at.is_(None))
    count_query = (
        select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
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
    if channel is not None:
        query = query.where(Document.channel == channel)
        count_query = count_query.where(Document.channel == channel)
    if not include_superseded:
        replaced = select(Document.supersedes_id).where(
            Document.supersedes_id.is_not(None), Document.deleted_at.is_(None)
        )
        query = query.where(Document.id.not_in(replaced))
        count_query = count_query.where(Document.id.not_in(replaced))
    total = (await db.exec(count_query)).one()
    rows = (
        await db.exec(
            query.order_by(Document.created_at.desc(), Document.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), int(total)


async def store_summary(
    db: AsyncSession, *, owner_user_id: int | None = None
) -> dict[str, Any]:
    """What the card shows: how much paper, how recent, how heavy."""
    live = Document.deleted_at.is_(None)
    if owner_user_id is not None:
        live = live & (Document.owner_user_id == owner_user_id)
    by_kind = (
        await db.exec(
            select(
                Document.kind,
                func.count(),
                func.coalesce(func.sum(Document.byte_size), 0),
            )
            .where(live)
            .group_by(Document.kind)
        )
    ).all()
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = (
        await db.exec(
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
    db: AsyncSession, *, owner_user_id: int | None = None
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
        await db.exec(
            query.group_by(DocumentTag.label).order_by(
                func.count().desc(), DocumentTag.label
            )
        )
    ).all()
    return [(str(label), int(n)) for label, n in rows]


async def tags_for_many(
    db: AsyncSession, document_ids: list[int]
) -> dict[int, list[str]]:
    """Tags for a page of documents in ONE query.

    A per-row lookup is the N+1 the house rules forbid, and a listing
    endpoint is exactly where it bites.
    """
    if not document_ids:
        return {}
    rows = (
        await db.exec(
            select(DocumentTag)
            .where(DocumentTag.document_id.in_(document_ids))
            .order_by(DocumentTag.document_id, DocumentTag.label)
        )
    ).all()
    grouped: dict[int, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.document_id, []).append(row.label)
    return grouped


async def tags_for(db: AsyncSession, document_id: int) -> list[str]:
    rows = (
        await db.exec(
            select(DocumentTag)
            .where(DocumentTag.document_id == document_id)
            .order_by(DocumentTag.label)
        )
    ).all()
    return [row.label for row in rows]
