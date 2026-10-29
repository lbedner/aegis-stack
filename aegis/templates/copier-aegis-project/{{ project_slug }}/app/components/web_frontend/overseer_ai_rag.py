"""The Overseer AI page's RAG sections.

Knowledge: how the index is set up (embeddings, chunking, where it lives,
anything misconfigured) and what it holds, each collection's files in the
drawer. Filled from here: a new collection, parts of this app picked (the
twin knows their code) and files uploaded, a source removed, one or every
source re-indexed, the collection deleted. Search: ask the index a question and
see the ranked chunks it hands back, the quickest way to see what an agent
retrieves. A window onto the RAG service as it is (plain vector search),
through the backend's one ``rag_service``. File-based (Chroma), so offered
whenever RAG is installed, database or not.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.services.system.jobs import get_job_runner

from .overseer_ai_common import PARTIALS, section_url
from .overseer_code import file_url
from .overseer_live import frame
from .rendering import drawer_state, fragment, hx_dialog, hx_post, with_query

COLLECTION_PARAM = "collection"
SOURCES_URL = f"{PARTIALS}/sources"  # where the sources dialog posts
TOP_K_CHOICES = (3, 5, 10, 20)
# A collection's indexing job on its drawer: pushed as it changes (``JOB_EVENT``),
# the stream closed once it ends (``JOB_DONE``); how far, read off its label.
JOB_EVENT = "ai-collection-job"
JOB_DONE = "ai-collection-job-done"
JOB_TEMPLATE = "pages/overseer/ai/_collection_job.html"


def _service() -> Any:
    """The RAG service, imported when used: this module ships wherever the
    Overseer does, RAG or not."""
    from app.services.rag.config import get_rag_service

    return get_rag_service()


async def collection_stats() -> list[Any]:
    """Every collection's counts (``rag.collections``), each a
    ``CollectionInfo``."""
    from app.services.rag.collections import collection_stats as every

    return await every()


def service_status() -> tuple[dict[str, Any], list[str]]:
    """The index's configuration, and what is wrong with it."""
    service = _service()
    return service.get_service_status(), service.validate_service()


async def collection_files(name: str) -> list[Any]:
    return await _service().list_files(name)


async def delete_collection(name: str) -> bool:
    return await _service().delete_collection(name)


async def collection_names() -> list[str]:
    return await _service().list_collections()


async def sources_context(name: str | None) -> dict[str, Any]:
    """The steps to fill a collection (``name``, or a new one): what of this
    app can be known (``rag.knowable``), how big a chunk is (what the size
    estimate divides by), what a name may be, and whether indexing will
    embed on this server's CPU (a local model, no worker to spread it)."""
    from app.services.rag import embedding, knowable
    from app.services.rag.uploads import NAMED, PATTERN

    config = _service().config
    local = config.embedding_provider == "sentence-transformers"
    return {
        "name": name,
        "add_url": SOURCES_URL,
        "knowable": await asyncio.to_thread(knowable.knowable),
        "chunk_size": config.chunk_size,
        "slow": local and not embedding.workers(),
        "named": NAMED,
        "name_pattern": PATTERN,
    }


async def start_adding(
    collection: str,
    uploads: list[tuple[str, bytes]],
    picked: list[str],
    extensions: list[str],
) -> str:
    """Files uploaded, and the parts picked read for ``extensions``, added
    as a background job (``rag.sources``): its id. No type ticked reads no
    part. ValueError for what cannot be, at once."""
    from app.services.rag import sources

    the = await sources.plan(
        collection,
        uploads=uploads,
        parts=picked if extensions else [],
        extensions=extensions,
    )
    return sources.start(the)


async def remove_source(collection: str, source: str) -> Any:
    return await _service().remove_file(source, collection)


async def start_reindex(collection: str, source: str | None = None) -> str:
    """Every source re-indexed (or ``source`` alone), as a background job:
    its id."""
    from app.services.rag import sources

    return sources.start(await sources.held(collection, source))


def last_job(collection: str) -> Any:
    from app.services.rag import sources

    return sources.last_job(collection)


def idle(collection: str) -> None:
    """ValueError while ``collection`` is being indexed (``rag.sources``)."""
    from app.services.rag import sources

    sources.idle(collection)


def job_view(collection: str, job: dict[str, Any]) -> dict[str, Any]:
    """A collection's indexing job as its drawer shows it: running (how far,
    and the stream to follow it on), or how it ended."""
    from app.services.rag import sources

    status, label = job["status"], job["label"]
    title = {"running": "Indexing", "failed": "Failed"}.get(status, "Done")
    view = {"status": status, "title": title, "label": label, "ratio": None}
    if status == "running":
        if found := sources.progress_of(label):
            done, total = found
            view["ratio"] = done / max(total, 1)
        events = f"{PARTIALS}/collections/{collection}/jobs/{job['job_id']}/events"
        return view | {"events": events, "event": JOB_EVENT, "done": JOB_DONE}
    if status == "failed":
        return view | {"label": job["error"] or "Indexing failed", "tone": "error"}
    done = job["result"] or {}
    said = f"{done.get('files', 0):,} files, {done.get('chunks', 0):,} chunks."
    if unread := done.get("unread") or []:
        said += f" Could not read: {sources.some(unread)}"
        return view | {"label": said, "tone": "warn"}
    return view | {"label": said, "tone": "muted"}


async def job_events(collection: str, job_id: str) -> AsyncIterator[str]:
    """A collection's indexing job over SSE, pushed as it changes (the job
    runner's own updates, nothing polled): its state each time, the last
    one loading the drawer again, then ``JOB_DONE``, which closes the
    stream."""
    runner = get_job_runner()
    queue = await runner.subscribe_any(job_id)
    if queue is None:
        return
    async for snapshot in runner.follow(job_id, queue):
        job = job_view(collection, snapshot)
        html = fragment(JOB_TEMPLATE, job=job, drawer=drawer_url(collection))
        yield frame(JOB_EVENT, html)
    yield frame(JOB_DONE, "done")


def drawer_url(collection: str) -> str:
    return f"{PARTIALS}/collections/{collection}/drawer"


def collection_url(collection: str) -> str:
    """The Knowledge page with ``collection``'s drawer open."""
    return section_url("knowledge", **{COLLECTION_PARAM: collection})


async def search(**query: Any) -> list[Any]:
    return await _service().search(**query)


async def knowledge_context(query: Any) -> dict[str, Any]:
    status, problems = service_status()
    collections = await collection_stats()
    wanted = query.get(COLLECTION_PARAM) or ""
    return drawer_state(COLLECTION_PARAM, drawer_url(wanted) if wanted else None) | {
        "figures": [
            {"label": "Collections", "value": len(collections)},
            {"label": "Chunks", "value": f"{sum(c.count for c in collections):,}"},
            {
                "label": "Documents",
                "value": f"{sum(c.doc_count for c in collections):,}",
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
        "new": hx_dialog(f"{PARTIALS}/collections/new", "data-write"),
        "rows": [
            {
                "name": {"label": c.name, "url": collection_url(c.name)},
                "chunks": c.count,
                "documents": c.doc_count,
            }
            for c in collections
        ],
    }


async def collection_context(name: str) -> dict[str, Any] | None:
    """A collection's drawer, or None when the index holds nothing of it
    and none is being made or failed to be (a new one has no collection
    until a batch is in; a deleted one, only its last job's record)."""
    job = last_job(name)
    files = await collection_files(name)
    if not files and not (job and job.status != "done"):
        return None
    removing = f"{PARTIALS}/collections/{name}/sources/remove"
    reindex = f"{PARTIALS}/collections/{name}/reindex"
    urls = await code_urls([f.source for f in files])
    return {
        "name": name,
        "files": [
            {
                "source": {"path": f.source, "url": url},
                "type": f.content_type,
                "chunks": f.chunks,
                "indexed": f.indexed_at,
                "reindex": hx_post(with_query(reindex, source=f.source), "data-write"),
                "remove": hx_dialog(
                    with_query(removing, source=f.source), "data-write"
                ),
            }
            for f, url in zip(files, urls, strict=True)
        ],
        "job": job_view(name, job.as_dict()) if job else None,
        "add": hx_dialog(f"{PARTIALS}/collections/{name}/add", "data-write"),
        "reindex": hx_post(reindex, "data-write"),
        "delete": hx_dialog(
            f"{PARTIALS}/collections/{name}/confirm-delete", "data-write"
        ),
    }


async def search_context() -> dict[str, Any]:
    return {
        "collections": [{"id": n, "name": n} for n in await collection_names()],
        "top_k": [{"id": str(k), "name": f"{k} results"} for k in TOP_K_CHOICES],
        "search_url": f"{PARTIALS}/rag/search",
    }


async def code_urls(sources: list[str]) -> list[str | None]:
    """Where each source opens in Overseer > Code, if it is the app's own:
    each is checked on disk (``file_url``), so off the loop, all at once."""
    return await asyncio.to_thread(lambda: [file_url(s) for s in sources])


async def result_rows(results: list[Any]) -> list[dict[str, Any]]:
    paths = [(r.metadata or {}).get("source") or "" for r in results]
    urls = await code_urls(paths)
    return [
        {
            "rank": r.rank,
            "score": f"{r.score:.2f}",
            "source": {"path": path, "url": url} if path else None,
            "content": r.content,
        }
        for r, path, url in zip(results, paths, urls, strict=True)
    ]
