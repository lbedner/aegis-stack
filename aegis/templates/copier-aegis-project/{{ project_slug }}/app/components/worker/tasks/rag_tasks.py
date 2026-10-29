"""Embedding a batch of files for the knowledge base, as a worker task
(arq form): the vectors go back through Redis to the one process that
writes the index. The RAG service is imported lazily: a worker stack
without it still imports this module and never receives the task."""

from typing import Any


async def embed_files_task(
    ctx: dict[str, Any], key: str, n: int, files: list[str]
) -> None:
    from app.services.rag.embedding import embed_batch

    await embed_batch(key, n, files)
