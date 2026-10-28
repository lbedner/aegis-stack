"""Files read, chunked and embedded apart from where they are stored.

Embedded Chroma is safe in one process only, so one process writes the
index; the embedding, which is the slow part, need not be there. With a
worker, each batch of files is a task on the system queue, and its
vectors come back through Redis to the process that stores them. Without
one, the batches are embedded in this process, one at a time: slow on
CPU, so a worker or a hosted embedding provider is the fix.

``IN_FLIGHT`` batches are out at a time: a worker process embeds one
batch at a time (one model, one lock), so more out would only wait in the
queue, and the batches waiting in Redis for the writer stay few."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from importlib.util import find_spec
from typing import Any
import uuid

from app.core import cpus
from app.core.key_family import KeyFamily
from app.core.log import logger
from app.services.rag.config import get_rag_service
from app.services.rag.models import Document, EmbeddedBatch

BATCH = 50  # files read, chunked and embedded at a time
# ponytail: fixed; size it from the system queue's worker count if many run.
IN_FLIGHT = 4
KEY = "rag:embedded:"  # a run's batches: this, then the run's id
KEEP_SECONDS = 3600
WAIT_SECONDS = 600  # a batch not back by then: nothing is taking them

REDIS_KEYS = (
    KeyFamily(
        f"{KEY}*",
        "list",
        "Embedded batches",
        "One list per indexing run: batches a worker embedded, waiting for "
        "the process that writes the index; expires with the run",
        "RAG",
        columns=("Index", "Batch"),
        # Chunks of whatever was indexed, private documents included.
        peek=False,
        holds="batch",
    ),
)


def workers() -> bool:
    """Whether this stack has a worker to hand batches to; asked each run,
    so a worker added later is used."""
    return find_spec("app.components.worker.pools") is not None


async def embedded(
    files: list[str], here: frozenset[str] = frozenset()
) -> AsyncIterator[tuple[int, EmbeddedBatch]]:
    """``files`` embedded ``BATCH`` at a time, each batch as it is ready
    with how many files are done. Those ``here`` (kept uploads, which only
    this process is sure to see) are embedded in this process, as all are
    without a worker; the rest go to the workers, first, so they are busy
    while this process embeds its own."""
    away = workers()
    local = [f for f in files if not away or f in here]
    sent = [f for f in files if away and f not in here]
    done = 0
    async for size, batch in _from_workers(_split(sent)):
        done += size
        yield done, batch
    for batch in _split(local):
        done += len(batch)
        yield done, await embed_files(batch)


async def embed_files(files: list[str]) -> EmbeddedBatch:
    """Read, chunk and embed ``files``; one that cannot be read is missed,
    an empty one (an ``__init__.py``) passed over: the loader loads it as
    nothing."""
    service = get_rag_service()
    loaded = await asyncio.gather(
        *(service.load_documents(f) for f in files), return_exceptions=True
    )
    documents: list[Document] = []
    missed: list[str] = []
    for path, found in zip(files, loaded, strict=True):
        if isinstance(found, BaseException):
            logger.warning("rag.unread", path=path, error=str(found))
            missed.append(path)
        else:
            documents += found
    return EmbeddedBatch(
        read=list(dict.fromkeys(d.metadata["source"] for d in documents)),
        missed=missed,
        embedded=await service.vectorstore.embed(
            await service.chunk_documents(documents)
        ),
    )


async def embed_batch(key: str, n: int, files: list[str]) -> None:
    """A worker's task: embed batch ``n`` (``files``) and hand it back at
    ``key``. A failure is handed back too, so the writer stops at once
    rather than waiting ``WAIT_SECONDS`` for a batch that will never come."""
    # Nothing else in a worker waits on a person: every CPU it has embeds.
    get_rag_service().vectorstore.threads = cpus.allowed()
    try:
        batch = (await embed_files(files)).model_copy(update={"n": n})
    except Exception as exc:
        logger.exception("rag.embed_failed", batch=n, files=len(files))
        batch = EmbeddedBatch(n=n, error=f"{type(exc).__name__}: {exc}")
    redis = _redis()
    try:
        pipe = redis.pipeline()
        pipe.rpush(key, batch.model_dump_json())
        pipe.expire(key, KEEP_SECONDS)
        await pipe.execute()
    finally:
        await redis.aclose()


async def _from_workers(
    batches: list[list[str]],
) -> AsyncIterator[tuple[int, EmbeddedBatch]]:
    """``batches`` handed to the workers, ``IN_FLIGHT`` at a time, each
    yielded (with its size) as it comes back, in whatever order. Each is
    known by its number, so one handed back twice (a task retried after it
    answered) is dropped, and a run ends only once every batch is in."""
    if not batches:
        return
    key = f"{KEY}{uuid.uuid4().hex}"
    waiting = deque(enumerate(batches))
    outstanding = set(range(len(batches)))
    redis = _redis()
    try:
        for _ in range(min(IN_FLIGHT, len(waiting))):
            await _enqueue(key, *waiting.popleft())
        while outstanding:
            got = await redis.blpop([key], timeout=WAIT_SECONDS)
            if got is None:
                raise TimeoutError(
                    f"{len(outstanding)} of {len(batches)} batches did not come "
                    f"back in {WAIT_SECONDS // 60} minutes: is the system "
                    "worker running?"
                )
            batch = EmbeddedBatch.model_validate_json(got[1])
            if batch.n not in outstanding:
                logger.info("rag.embedded_again", batch=batch.n)
                continue
            if batch.error:
                raise RuntimeError(f"A worker could not embed a batch: {batch.error}")
            outstanding.discard(batch.n)
            if waiting:
                await _enqueue(key, *waiting.popleft())
            yield len(batches[batch.n]), batch
    finally:
        await redis.delete(key)
        await redis.aclose()


async def _enqueue(key: str, n: int, files: list[str]) -> None:
    from app.components.worker import pools
    from app.core.constants import QueueName

    await pools.enqueue_task("embed_files_task", QueueName.SYSTEM, key, n, files)


def _redis() -> Any:
    import redis.asyncio as aioredis

    from app.services.system.redis_keys import redis_url

    return aioredis.from_url(redis_url(), decode_responses=True)


def _split(files: list[str]) -> list[list[str]]:
    return [files[n : n + BATCH] for n in range(0, len(files), BATCH)]
