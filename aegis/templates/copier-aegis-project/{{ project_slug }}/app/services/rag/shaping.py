"""Chroma-shaped in, Chroma-shaped out.

Chunks prepared for the store (``prepare``: ids, texts, metadata), metadata
coercion, the where clause, and collapsing several chunks of one document
down to its best hit. None of it touches the store, so none of it needs
the manager.
"""

from typing import Any

from app.core.time import utcnow

from .ids import generate_chunk_id
from .models import Document, Embedded, SearchResult


def deduplicate_results(results: list[SearchResult], top_k: int) -> list[SearchResult]:
    """
    Remove near-duplicate results, keeping highest scored.

    Uses source file + start line as fingerprint. Chunks from the same
    location are considered duplicates regardless of slight content differences.

    Args:
        results: Search results to deduplicate
        top_k: Maximum results to return

    Returns:
        Deduplicated results sorted by score
    """
    seen_content: dict[str, SearchResult] = {}

    for result in results:
        # Use source file + start line as fingerprint
        source = result.metadata.get("source", "")
        start_line = result.metadata.get("start_line", 0)
        fingerprint = f"{source}:{start_line}"

        if fingerprint not in seen_content:
            seen_content[fingerprint] = result
        elif result.score > seen_content[fingerprint].score:
            # Keep higher scored version
            seen_content[fingerprint] = result

    # Sort by score descending, re-rank, and limit to top_k
    deduped = sorted(seen_content.values(), key=lambda r: r.score, reverse=True)
    for i, result in enumerate(deduped):
        result.rank = i + 1

    return deduped[:top_k]


def clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Clean metadata for ChromaDB compatibility."""
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, str | int | float | bool):
            clean[key] = value
        elif value is None:
            continue
        else:
            # Convert other types to string
            clean[key] = str(value)
    return clean


def build_where_clause(filter_metadata: dict[str, Any]) -> dict[str, Any]:
    """Build ChromaDB where clause from filter."""
    # Simple equality filter
    if len(filter_metadata) == 1:
        key, value = next(iter(filter_metadata.items()))
        return {key: value}

    # Multiple conditions with AND
    conditions = []
    for key, value in filter_metadata.items():
        conditions.append({key: value})

    return {"$and": conditions}


def prepare(documents: list[Document], fields: list[str] | None = None) -> Embedded:
    """Chunks as the store keeps them, not yet embedded: each one's id (by
    its source and place in it, so indexing a file again replaces its
    chunks), text, and metadata (only ``fields``, given them; when it was
    indexed, always: what the index holds and since when is its own)."""
    indexed_at = utcnow().isoformat()
    ids, texts, metadatas = [], [], []
    for i, doc in enumerate(documents):
        source = doc.metadata.get("source", f"unknown_{i}")
        ids.append(generate_chunk_id(source, doc.metadata.get("chunk_index", i)))
        texts.append(doc.content)
        kept = {k: v for k, v in doc.metadata.items() if not fields or k in fields}
        metadatas.append(clean_metadata({**kept, "indexed_at": indexed_at}))
    return Embedded(ids=ids, texts=texts, metadatas=metadatas)
