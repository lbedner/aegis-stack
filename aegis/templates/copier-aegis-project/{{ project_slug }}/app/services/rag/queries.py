"""The knowledge base's reads (``models.knowledge``): its records, as
``knowledge.sync`` keeps them."""

from collections.abc import Sequence

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.rag.models.knowledge import KnowledgeBase, KnowledgeBaseSource


async def knowledge_bases(session: AsyncSession) -> list[KnowledgeBase]:
    """Every knowledge base, by name."""
    found = await session.exec(select(KnowledgeBase).order_by(KnowledgeBase.name))
    return list(found.all())


async def sources_of(
    session: AsyncSession, bases: Sequence[KnowledgeBase]
) -> list[KnowledgeBaseSource]:
    """The sources of ``bases``, by path."""
    ids = [base.id for base in bases]
    found = await session.exec(
        select(KnowledgeBaseSource)
        .where(col(KnowledgeBaseSource.knowledge_base_id).in_(ids))
        .order_by(KnowledgeBaseSource.file_path)
    )
    return list(found.all())
