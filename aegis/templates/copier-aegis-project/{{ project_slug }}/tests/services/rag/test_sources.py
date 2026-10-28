"""A knowledge base's sources (``rag.sources``): files uploaded, kept beside
the index (never anywhere else) and indexed; paths the server holds, files
or folders (filtered by extension, some left out), added to the collection
or replacing it, nothing changed until something is read; and every
source read again by a reindex. The API and Overseer both go through it."""

from pathlib import Path
from typing import Any

import pytest

from app.services.rag import embedding, sources
from app.services.rag.loaders import DEFAULT_EXTENSIONS
from app.services.rag.models import Indexed, IndexedFile
from app.services.rag.service import LoaderError
from tests.services.rag.fakes import FakeIndex, fake_paths_of


async def added(collection: str, **asked: Any) -> Indexed:
    """Sources planned and indexed now, as the API adds them."""
    return await sources.index(await sources.plan(collection, **asked))


@pytest.mark.asyncio
async def test_uploads_are_kept_and_indexed(index: FakeIndex, tmp_path: Path) -> None:
    """One that cannot be read is named, and not kept."""
    done = await added(
        "default",
        uploads=[
            ("refunds.md", b"Within 14 days."),
            ("unreadable.bin", b"\x00"),
            ("returns.md", b"Boxed."),
        ],
    )

    folder = tmp_path / "sources" / "default"
    assert (folder / "refunds.md").read_bytes() == b"Within 14 days."
    assert not (folder / "unreadable.bin").exists()
    kept = [str(folder / "refunds.md"), str(folder / "returns.md")]
    assert index.indexed == [(kept, "default")]
    assert (done.files, done.chunks, done.unread) == (2, 4, ["unreadable.bin"])


@pytest.mark.asyncio
async def test_an_upload_never_lands_outside_its_knowledge_base(
    index: FakeIndex, tmp_path: Path
) -> None:
    """A name that climbs, or names a drive, is kept by its last part, in
    its own folder; a collection that would climb is refused, nothing kept."""
    await added("default", uploads=[("../../etc/passwd", b"x"), ("C:evil.md", b"x")])
    with pytest.raises(ValueError):
        await added("..escape", uploads=[("a.md", b"x")])

    folder = tmp_path / "sources" / "default"
    assert index.indexed == [
        ([str(folder / "passwd"), str(folder / "evil.md")], "default")
    ]


@pytest.mark.asyncio
async def test_a_folder_the_server_holds_is_added_to_the_collection(
    index: FakeIndex,
) -> None:
    """Read as ``rag index`` reads it; its files' old chunks go first, in
    one call, so a file that shrank leaves none; the other sources stay."""
    index.folders["/srv/docs"] = ["/srv/docs/a.md", "/srv/docs/b.md"]

    done = await added(
        "default",
        paths=[" /srv/docs "],
        extensions=[".md", ".py"],
        exclude=["**/drafts/*"],
    )

    assert index.listed == [("/srv/docs", [".md", ".py"], ["**/drafts/*"])]
    assert index.cleared == [("default", ["/srv/docs/a.md", "/srv/docs/b.md"])]
    assert index.removed == [] and index.deleted == []
    assert (done.files, done.chunks, done.unread) == (2, 4, [])


@pytest.mark.asyncio
async def test_replacing_a_collection_lets_the_rest_go_after(
    index: FakeIndex,
) -> None:
    """What ``rag index`` does, but only once the new sources are in."""
    index.folders["/srv/docs"] = ["/srv/docs/a.md"]
    index.held = [
        IndexedFile(source="/srv/docs/a.md", chunks=2),
        IndexedFile(source="/old/b.md", chunks=1),
    ]

    await added("default", paths=["/srv/docs"], replace=True)

    assert index.indexed == [(["/srv/docs/a.md"], "default")]
    assert index.cleared[-1] == ("default", ["/old/b.md"])  # the rest, at once


@pytest.mark.asyncio
async def test_nothing_changes_until_something_is_read(index: FakeIndex) -> None:
    index.folders["/srv/empty"] = []
    index.held = [IndexedFile(source="/old/b.md", chunks=1)]

    for asked in (
        {"paths": ["/srv/missing"], "replace": True},
        {"paths": ["/srv/empty"], "replace": True},
        {"uploads": [("unreadable.bin", b"\x00")], "replace": True},
    ):
        with pytest.raises(LoaderError):
            await added("default", **asked)
    with pytest.raises(ValueError):
        await added("default", paths=[" "])

    assert index.cleared == [] and index.indexed == [] and index.removed == []


@pytest.mark.asyncio
async def test_a_part_of_this_app_is_read_by_its_files(
    index: FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The twin names a part's files (``knowable.paths_of``), of the types
    asked, the loader's own when none are: what the API and Overseer pass."""
    asked = fake_paths_of(monkeypatch, "/code/app/services/ai/chat.py")

    await added("default", parts=["service:ai"], extensions=[".md"])
    await added("default", parts=["service:ai"])

    assert asked[0] == (["service:ai"], [".md"])
    assert asked[1] == (["service:ai"], DEFAULT_EXTENSIONS)
    assert index.indexed[0] == (["/code/app/services/ai/chat.py"], "default")


@pytest.mark.asyncio
async def test_files_are_read_and_stored_a_batch_at_a_time(
    index: FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """However much is picked, one batch is in memory: read, chunked,
    embedded and stored, then the next; how far it has got, said each time."""
    monkeypatch.setattr(embedding, "BATCH", 2)
    index.folders["/srv/docs"] = [f"/srv/docs/{n}.md" for n in range(5)]
    said: list[str] = []

    the = await sources.plan("default", paths=["/srv/docs"])
    done = await sources.index(the, said.append)

    assert [len(held) for held, _ in index.indexed] == [2, 2, 1]
    assert said == [f"Indexing {n} of 5 files..." for n in (2, 4, 5)]
    assert (done.files, done.chunks) == (5, 10)


@pytest.mark.asyncio
async def test_indexing_runs_as_a_job_one_per_collection(
    index: FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What Overseer starts: the refusals at once, the reading in the
    background, its end kept for the drawer; a second while one runs refused."""
    from app.services.system.jobs import get_job_runner

    index.folders["/srv/docs"] = ["/srv/docs/a.md"]
    with pytest.raises(ValueError):
        await sources.plan("default")

    job_id = sources.start(await sources.plan("default", paths=["/srv/docs"]))
    ended = await get_job_runner().wait(job_id)

    assert ended.status == "done" and ended.result == {
        "files": 1,
        "chunks": 2,
        "unread": [],
    }
    assert sources.last_job("default").job_id == job_id  # type: ignore[union-attr]

    def running(collection: str) -> object:
        return type("Job", (), {"status": "running", "label": "Indexing 1 of 9"})()

    monkeypatch.setattr(sources, "last_job", running)
    with pytest.raises(ValueError, match="being indexed already"):
        sources.start(await sources.held("default"))


@pytest.mark.asyncio
async def test_a_picker_left_empty_adds_no_upload(index: FakeIndex) -> None:
    """A form's empty file field arrives as a file with no name."""
    index.folders["/srv/docs"] = ["/srv/docs/a.md"]

    the = await sources.plan("default", uploads=[("", b"")], paths=["/srv/docs"])

    assert the.files == ["/srv/docs/a.md"]


@pytest.mark.asyncio
async def test_a_name_the_index_cannot_take_is_refused_at_once(
    index: FakeIndex,
) -> None:
    """Before anything is read or embedded, not once the first batch is in."""
    index.folders["/srv/docs"] = ["/srv/docs/a.md"]

    with pytest.raises(ValueError, match="Source Code"):
        await sources.plan("Source Code", paths=["/srv/docs"])
    assert index.listed == []


def test_a_listed_field_reads_as_the_cli_reads_it() -> None:
    assert sources.listed("py, .md ,", dotted=True) == [".py", ".md"]
    assert sources.listed("**/test_*, *.lock") == ["**/test_*", "*.lock"]
    assert sources.listed(" ") == []


@pytest.mark.asyncio
async def test_a_reindex_reads_every_source_again(index: FakeIndex) -> None:
    """A source that can no longer be read is named, not a failure; read
    in batches, as adding is."""
    index.held = [
        IndexedFile(source="/srv/docs/a.md", chunks=2),
        IndexedFile(source="/srv/docs/moved.md", chunks=1),
    ]

    done = await sources.index(await sources.held("default"))

    assert index.indexed == [(["/srv/docs/a.md"], "default")]  # batched, as adding
    assert (done.files, done.chunks, done.unread) == (1, 2, ["/srv/docs/moved.md"])


@pytest.mark.asyncio
async def test_one_source_is_read_again_only_if_the_collection_holds_it(
    index: FakeIndex,
) -> None:
    index.held = [IndexedFile(source="/srv/docs/a.md", chunks=2)]

    assert (await sources.held("default", "/srv/docs/a.md")).files == ["/srv/docs/a.md"]
    with pytest.raises(ValueError, match="/etc/hosts"):
        await sources.held("default", "/etc/hosts")
