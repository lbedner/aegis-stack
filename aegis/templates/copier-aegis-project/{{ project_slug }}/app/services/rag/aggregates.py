"""What the knowledge index holds, as figures (``app.core.aggregates``):
each collection's chunks and files, never a chunk. Read from the vector
store, not the database, and over all time: a chunk carries no date."""

from pydantic import BaseModel

from app.core.aggregates import Aggregate
from app.core.figures import FIGURES
from app.services.rag.collections import collection_stats


class KnowledgeCollections(BaseModel):
    """Chunks and source files in each collection."""

    model_config = FIGURES

    chunks: dict[str, int]
    files: dict[str, int]


async def collections(session: None, days: int | None) -> KnowledgeCollections:
    found = await collection_stats()
    return KnowledgeCollections(
        chunks={c.name: c.count for c in found},
        files={c.name: c.doc_count for c in found},
    )


AGGREGATES = (
    Aggregate(
        "collections",
        "Knowledge chunks and files by collection (all time: chunks carry no date)",
        collections,
        database=False,
        dated=False,
    ),
)
