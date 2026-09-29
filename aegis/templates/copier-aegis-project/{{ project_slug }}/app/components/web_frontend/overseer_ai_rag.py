"""The Overseer AI page's RAG sections.

Knowledge: how the index is set up (embeddings, chunking, where it lives,
anything misconfigured) and what it holds, each collection's files in the
drawer and the collection deletable. Search: ask the index a question and
see the ranked chunks it hands back, the quickest way to see what an agent
retrieves. A window onto the RAG service as it is (plain vector search),
through the backend's one ``rag_service``. File-based (Chroma), so offered
whenever RAG is installed, database or not.
"""

from typing import Any

from .overseer_ai_common import PARTIALS, section_url
from .rendering import drawer_state, hx_dialog

COLLECTION_PARAM = "collection"
TOP_K_CHOICES = (3, 5, 10, 20)


def _service() -> Any:
    from app.components.backend.api.rag.routes import rag_service

    return rag_service


def service_status() -> tuple[dict[str, Any], list[str]]:
    """The index's configuration, and what is wrong with it."""
    service = _service()
    return service.get_service_status(), service.validate_service()


async def collection_stats() -> list[dict[str, Any]]:
    """Every collection with its chunk and document counts."""
    service = _service()
    stats = [
        await service.get_collection_stats(n) for n in await service.list_collections()
    ]
    return [s for s in stats if s]


async def collection_files(name: str) -> list[Any]:
    return await _service().list_files(name)


async def delete_collection(name: str) -> bool:
    return await _service().delete_collection(name)


async def search(**query: Any) -> list[Any]:
    return await _service().search(**query)


async def knowledge_context(query: Any) -> dict[str, Any]:
    status, problems = service_status()
    collections = await collection_stats()
    wanted = query.get(COLLECTION_PARAM) or ""
    return drawer_state(
        COLLECTION_PARAM, f"{PARTIALS}/collections/{wanted}/drawer" if wanted else None
    ) | {
        "figures": [
            {"label": "Collections", "value": len(collections)},
            {"label": "Chunks", "value": f"{sum(c['count'] for c in collections):,}"},
            {
                "label": "Documents",
                "value": f"{sum(c.get('doc_count', 0) for c in collections):,}",
            },
        ],
        "setup": [
            ("Embeddings", status.get("embedding_provider")),
            ("Model", status.get("embedding_model")),
            ("Chunk size", status.get("chunk_size")),
            ("Chunk overlap", status.get("chunk_overlap")),
            ("Results by default", status.get("default_top_k")),
            ("Stored in", status.get("persist_directory")),
            ("Last activity", status.get("last_activity")),
        ],
        "problems": problems,
        "rows": [
            {
                "name": {
                    "label": c["name"],
                    "url": section_url("knowledge", **{COLLECTION_PARAM: c["name"]}),
                },
                "chunks": c["count"],
                "documents": c.get("doc_count", 0),
            }
            for c in collections
        ],
    }


async def collection_context(name: str) -> dict[str, Any]:
    files = await collection_files(name)
    return {
        "name": name,
        "files": [{"source": f.source, "chunks": f.chunks} for f in files],
        "delete": hx_dialog(f"{PARTIALS}/collections/{name}/confirm-delete"),
    }


async def search_context() -> dict[str, Any]:
    return {
        "collections": [
            {"id": c["name"], "name": c["name"]} for c in await collection_stats()
        ],
        "top_k": [{"id": str(k), "name": f"{k} results"} for k in TOP_K_CHOICES],
        "search_url": f"{PARTIALS}/rag/search",
    }


def result_rows(results: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "rank": r.rank,
            "score": f"{r.score:.2f}",
            "source": (r.metadata or {}).get("source"),
            "content": r.content,
        }
        for r in results
    ]
