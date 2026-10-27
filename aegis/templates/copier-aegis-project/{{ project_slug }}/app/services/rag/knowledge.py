"""The knowledge base's records, kept to the index.

The index is the truth, read through ``RAGService`` whatever vector store
backs it: whatever wrote to it, the CLI, the API or Overseer, the records
follow. ``sync`` makes a ``knowledge_base`` of each
collection and a ``knowledge_base_source`` of each file indexed into it,
and drops what left; ``current`` syncs, then reads. Two first reads at
once may both make a knowledge base: the unique name refuses one.
"""

from collections import defaultdict
from datetime import datetime
from pathlib import PurePath

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.rag import queries
from app.services.rag.config import get_rag_service
from app.services.rag.models import IndexedFile
from app.services.rag.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseSource,
    KnowledgeRecord,
    SourceRecord,
)


async def sync(
    session: AsyncSession,
) -> list[tuple[KnowledgeBase, list[KnowledgeBaseSource]]]:
    """Bring the records up to the index: one knowledge base per
    collection, one source per file in it, nothing that left. Hands back
    what it kept, by name, so a reader need not read them again."""
    index = get_rag_service()
    held = await index.list_collections()
    bases = {base.name: base for base in await queries.knowledge_bases(session)}
    sources = await queries.sources_of(session, list(bases.values()))
    gone = [base for name, base in bases.items() if name not in held]
    gone_ids = {base.id for base in gone}
    for source in sources:
        if source.knowledge_base_id in gone_ids:
            await session.delete(source)
    await session.flush()  # its sources go first: they point at it
    for base in gone:
        await session.delete(base)
    kept = [bases.get(name) or KnowledgeBase(name=name) for name in held]
    session.add_all(kept)
    await session.flush()
    by_base: dict[int | None, dict[str | None, KnowledgeBaseSource]] = defaultdict(dict)
    for source in sources:
        by_base[source.knowledge_base_id][source.file_path] = source
    now = []
    for base in sorted(kept, key=lambda base: base.name):
        files = await index.list_files(base.name)
        now.append((base, await _sources(session, base, by_base[base.id], files)))
    await session.flush()
    return now


async def _sources(
    session: AsyncSession,
    base: KnowledgeBase,
    kept: dict[str | None, KnowledgeBaseSource],
    files: list[IndexedFile],
) -> list[KnowledgeBaseSource]:
    held = {found.source for found in files}
    for path, source in kept.items():
        if path not in held:
            await session.delete(source)
    now = []
    for found in sorted(files, key=lambda found: found.source):
        source = kept.get(found.source) or KnowledgeBaseSource(
            knowledge_base_id=base.id,
            name=PurePath(found.source).name,
            file_path=found.source,
        )
        source.content_type = found.content_type
        source.loaded = True
        source.meta_data = {
            **source.meta_data,
            "chunks": found.chunks,
            "indexed_at": found.indexed_at.isoformat() if found.indexed_at else None,
        }
        session.add(source)
        now.append(source)
    return now


async def current(session: AsyncSession) -> list[KnowledgeRecord]:
    """Every knowledge base and its sources, as the index holds them now."""
    return [
        KnowledgeRecord(
            name=base.name,
            description=base.description,
            sources=[_record(source) for source in sources],
        )
        for base, sources in await sync(session)
    ]


def _record(source: KnowledgeBaseSource) -> SourceRecord:
    stamp = source.meta_data.get("indexed_at")
    return SourceRecord(
        name=source.name,
        file_path=source.file_path,
        content_type=source.content_type,
        chunks=int(source.meta_data.get("chunks", 0)),
        indexed_at=datetime.fromisoformat(stamp) if stamp else None,
    )
