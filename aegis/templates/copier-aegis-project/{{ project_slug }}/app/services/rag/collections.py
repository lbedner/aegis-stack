"""The knowledge index's collections with their chunk and file counts:
the one home of those reads, for the health check, the Overseer, the CLI,
the API and the aggregate."""

from .config import get_rag_service
from .models import CollectionInfo


async def collection_info(name: str) -> CollectionInfo | None:
    """One collection's counts; None when there is no such collection."""
    return await get_rag_service().vectorstore.get_collection_info(name)


async def collection_stats() -> list[CollectionInfo]:
    """Every collection's counts, skipping one removed between the listing
    and its read."""
    names = await get_rag_service().list_collections()
    stats = [await collection_info(n) for n in names]
    return [s for s in stats if s]
