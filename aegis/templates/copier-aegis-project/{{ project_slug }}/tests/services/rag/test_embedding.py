"""Files embedded apart from where they are stored (``rag.embedding``): a
worker reads, chunks and embeds a batch and hands it back through Redis,
to the one process that writes the index; a batch no worker answers, or
one it could not embed, fails the run instead of hanging it; uploads,
kept where only this process is sure to see them, are embedded here."""

from pathlib import Path

import pytest

from app.core import cpus
from app.services.rag import embedding, sources
from app.services.rag.models import EmbeddedBatch, IndexedFile
from tests._fake_redis import FakeRedis
from tests.services.rag.fakes import FakeIndex


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    memory = FakeRedis()
    monkeypatch.setattr(embedding, "_redis", lambda: memory)
    return memory


def worker(
    monkeypatch: pytest.MonkeyPatch, twice: int | None = None
) -> list[list[str]]:
    """A worker that runs each batch the moment it is queued (batch
    ``twice`` twice, as a retry after its result was sent would); the
    batches it was handed."""
    handed: list[list[str]] = []

    async def enqueue(key: str, n: int, files: list[str]) -> None:
        handed.append(files)
        for _ in range(2 if n == twice else 1):
            await embedding.embed_batch(key, n, files)

    monkeypatch.setattr(embedding, "workers", lambda: True)
    monkeypatch.setattr(embedding, "_enqueue", enqueue)
    return handed


@pytest.mark.asyncio
async def test_a_worker_hands_its_batch_back_through_redis(
    index: FakeIndex, redis: FakeRedis
) -> None:
    await embedding.embed_batch("rag:embedded:run", 3, ["/srv/a.md", "/srv/moved.md"])

    [raw] = redis.lists["rag:embedded:run"]
    batch = EmbeddedBatch.model_validate_json(raw)
    assert (batch.n, batch.read, batch.missed) == (3, ["/srv/a.md"], ["/srv/moved.md"])
    assert len(batch.embedded.vectors) == 2  # its two chunks
    assert redis.ttl["rag:embedded:run"] == embedding.KEEP_SECONDS
    # Nothing else in a worker waits on a person: it embeds with every CPU.
    assert index.threads == cpus.allowed()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_an_empty_file_is_passed_over_not_called_unreadable(
    index: FakeIndex, tmp_path: Path
) -> None:
    """An empty ``__init__.py`` holds nothing to know: neither read nor
    missed; one that cannot be read still is."""
    empty = tmp_path / "__init__.py"
    empty.write_text("")

    batch = await embedding.embed_files([str(empty), "/srv/moved.md", "/srv/a.md"])

    assert (batch.read, batch.missed) == (["/srv/a.md"], ["/srv/moved.md"])


@pytest.mark.asyncio
async def test_the_workers_embed_and_this_process_stores(
    index: FakeIndex, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batches go out ``IN_FLIGHT`` at a time; an upload stays here; the
    run's key is gone once it is done."""
    monkeypatch.setattr(embedding, "BATCH", 2)
    handed = worker(monkeypatch)
    index.folders["/srv/docs"] = [f"/srv/docs/{n}.md" for n in range(5)]

    the = await sources.plan(
        "default", paths=["/srv/docs"], uploads=[("refunds.md", b"x")]
    )
    done = await sources.index(the)

    assert handed == [[f"/srv/docs/{n}.md" for n in p] for p in ((0, 1), (2, 3), (4,))]
    # The workers' batches first, so they are busy while this one embeds.
    assert [held for held, _ in index.indexed][-1] == [
        str(Path(index.config.persist_directory).parent / "sources/default/refunds.md")
    ]
    assert (done.files, done.chunks) == (6, 12)
    assert not any(redis.lists.values())


@pytest.mark.asyncio
async def test_a_reindex_keeps_its_uploads_here(
    index: FakeIndex, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Read again, an upload is still embedded where it is kept, never
    handed to a worker that may not see it; its name is the one it came as."""
    handed = worker(monkeypatch)
    kept = str((tmp_path / "sources" / "default" / "unreadable.bin").resolve())
    index.held = [
        IndexedFile(source="/srv/docs/a.md", chunks=2),
        IndexedFile(source=kept, chunks=1),
    ]

    done = await sources.index(await sources.held("default"))

    assert handed == [["/srv/docs/a.md"]]
    assert done.unread == ["unreadable.bin"]


@pytest.mark.asyncio
async def test_a_batch_handed_back_twice_is_stored_once(
    index: FakeIndex, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retry after its result was sent hands a batch back twice: the
    second is dropped, never counted for a batch still to come."""
    monkeypatch.setattr(embedding, "BATCH", 2)
    worker(monkeypatch, twice=0)
    index.folders["/srv/docs"] = [f"/srv/docs/{n}.md" for n in range(5)]

    done = await sources.index(await sources.plan("default", paths=["/srv/docs"]))

    assert [held for held, _ in index.indexed] == [
        [f"/srv/docs/{n}.md" for n in p] for p in ((0, 1), (2, 3), (4,))
    ]
    assert (done.files, done.chunks) == (5, 10)


@pytest.mark.asyncio
async def test_a_batch_no_worker_answers_fails_the_run(
    index: FakeIndex, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def lost(key: str, n: int, files: list[str]) -> None:
        return None

    monkeypatch.setattr(embedding, "workers", lambda: True)
    monkeypatch.setattr(embedding, "_enqueue", lost)
    index.folders["/srv/docs"] = ["/srv/docs/a.md"]

    with pytest.raises(TimeoutError, match="1 of 1 batches"):
        await sources.index(await sources.plan("default", paths=["/srv/docs"]))
    assert index.indexed == []


@pytest.mark.asyncio
async def test_a_batch_a_worker_could_not_embed_fails_the_run(
    index: FakeIndex, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker(monkeypatch)

    async def broken(documents: object) -> None:
        raise MemoryError("model too big")

    monkeypatch.setattr(index, "embed", broken)
    index.folders["/srv/docs"] = ["/srv/docs/a.md"]

    with pytest.raises(RuntimeError, match="model too big"):
        await sources.index(await sources.plan("default", paths=["/srv/docs"]))
    assert index.indexed == []
