"""A knowledge base's sources: files uploaded (kept beside the index, by
``uploads``), paths the server holds (files, or folders as ``rag index``
reads them) and parts of this app (``knowable``), added to the collection
or replacing it, or every source read again (``held``).

Planned first (``plan``: every refusal answered at once, uploads written
to disk, nothing read), then indexed a batch of files at a time
(``index``): read, chunked and embedded (by the workers, when there are
any: ``embedding``), stored here, then dropped, so however much is picked
only a few batches are ever in memory. The API indexes a plan and answers
once it is done; ``start`` indexes one as a background job in this process
(the one that writes the index), whose progress Overseer shows."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import re

from app.services.rag import embedding, knowable
from app.services.rag.config import get_rag_service
from app.services.rag.loaders import DEFAULT_EXTENSIONS
from app.services.rag.models import Indexed
from app.services.rag.service import LoaderError, RAGService
from app.services.rag.uploads import (
    check_name,
    forget_kept,
    keep,
    kept_at,
    kept_folder,
)
from app.services.system.jobs import JobHandle, JobSnapshot, get_job_runner

JOB = "rag-sources:"  # a collection's indexing job's name: this, then its name
# How far a job has got, as its label says it and as it is read back.
PROGRESS = re.compile(r"Indexing (\d+) of (\d+) files")
Report = Callable[[str], None]


def listed(text: str | None, *, dotted: bool = False) -> list[str]:
    """A comma-separated field as a list (empty for the loader's defaults);
    ``dotted`` reads extensions as the CLI does, ``"py, .md"`` as
    ``[".py", ".md"]``."""
    named = [e.strip() for e in (text or "").split(",") if e.strip()]
    return [e if e.startswith(".") else f".{e}" for e in named] if dotted else named


def progress(done: int, total: int) -> str:
    return f"Indexing {done} of {total} files..."


def progress_of(label: str) -> tuple[int, int] | None:
    """How many files of how many a job's label says are done, if it does."""
    found = PROGRESS.search(label)
    return (int(found[1]), int(found[2])) if found else None


def some(names: list[str]) -> str:
    """A few of ``names``, and how many more."""
    more = f" and {len(names) - 5} more" if len(names) > 5 else ""
    return ", ".join(names[:5]) + more


@dataclass(frozen=True)
class Plan:
    """What adding sources reads: every file, by path, and whether every
    other source then goes."""

    collection: str
    files: list[str]
    replace: bool = False


async def plan(
    collection: str,
    *,
    uploads: Sequence[tuple[str, bytes]] = (),
    paths: Sequence[str] = (),
    parts: Sequence[str] = (),
    extensions: Sequence[str] = (),
    exclude: Sequence[str] = (),
    replace: bool = False,
) -> Plan:
    """The files adding these sources reads: uploads (each a name and its
    bytes, kept to disk now, so their bytes go no further; a picker left
    empty sends one with no name, passed over), paths the server holds
    (files or folders) and parts of this app (by node id or ``docs``: the
    files each owns, by the twin), reading ``extensions`` (dotted; the
    loader's defaults when none) and leaving out ``exclude`` (globs, in
    place of the loader's own). Nothing is read yet.

    Every refusal is here, before anything changes: ValueError for a
    collection name the index cannot take, nothing to add, or a name an
    upload cannot be kept by; LoaderError (a ValueError too) for a path
    that is not there, or nothing to read at all."""
    check_name(collection)
    types, left_out = list(extensions) or None, list(exclude) or None
    named = [p.strip() for p in paths if p.strip()]
    uploads = [(n, b) for n, b in uploads if n]
    if not uploads and not named and not parts:
        raise ValueError("Send a file, a path or a part of this app.")
    service = get_rag_service()
    persist = service.config.persist_directory
    kept = [(kept_at(persist, collection, n), b) for n, b in uploads]
    files: list[str] = []
    if parts:
        picked = types or DEFAULT_EXTENSIONS
        files += await asyncio.to_thread(knowable.paths_of, parts, picked, left_out)
    for path in named:
        try:
            found = await asyncio.to_thread(service.loader.files, path, types, left_out)
        except FileNotFoundError as e:
            raise LoaderError(str(e)) from e
        files += [str(f) for f in found]
    for at, content in kept:
        await asyncio.to_thread(keep, at, content)
    files += [str(at) for at, _ in kept]
    if not files:
        raise LoaderError("Nothing to read in " + ", ".join([*named, *parts]))
    return Plan(collection, files, replace)


async def held(collection: str, source: str | None = None) -> Plan:
    """Every source ``collection`` holds (or ``source`` alone), to read
    again (after a change of model or chunking). ValueError for a
    ``source`` it does not hold: re-indexing reads only what is in."""
    files = [f.source for f in await get_rag_service().list_files(collection)]
    if source is None:
        return Plan(collection, files)
    if source not in files:
        raise ValueError(f"{collection} holds no {source}")
    return Plan(collection, [source])


async def index(the: Plan, report: Report | None = None) -> Indexed:
    """Read, chunk, embed and store ``the`` files a batch at a time, saying
    how far it has got to ``report``. A file's new chunks are stored over
    its old ones, then those it no longer makes go; with ``replace``, every
    other source goes once the new ones are in. Uploads
    (known by where they are kept) are embedded here, the one process sure
    to see them; one that cannot be read is named in ``unread`` and not
    kept. LoaderError when nothing could be read, nothing written then."""
    service = get_rag_service()
    folder = kept_folder(service.config.persist_directory, the.collection)
    here = frozenset(f for f in the.files if folder and Path(f).is_relative_to(folder))
    stored: list[str] = []
    unread: list[str] = []
    chunks = 0
    async for done, batch in embedding.embedded(the.files, here):
        unread += [Path(m).name if m in here else m for m in batch.missed]
        if folder and batch.missed:
            await asyncio.to_thread(forget_kept, batch.missed, folder)
        if report:
            report(progress(done, len(the.files)))
        if not batch.read:
            continue
        stats = await service.vectorstore.store(batch.embedded, the.collection)
        stored_now = set(batch.embedded.ids)
        await service.vectorstore.remove_by_source(
            the.collection, batch.read, keep=stored_now
        )
        stored += batch.read
        chunks += stats.documents_added
    if not stored:
        raise LoaderError("Nothing could be read: " + some(unread))
    if the.replace:
        await _forget_others(service, the.collection, set(stored))
    return Indexed(files=len(stored), chunks=chunks, unread=unread)


def idle(collection: str) -> None:
    """ValueError while ``collection`` is being indexed: one job at a time,
    and no deleting it under one (its next batch would make it again)."""
    running = last_job(collection)
    if running and running.status == "running":
        raise ValueError(f"{collection} is being indexed already: {running.label}")


def start(the: Plan) -> str:
    """Index ``the`` as a background job: its id. ValueError while one
    runs (``idle``), checked and started as one step (nothing awaited
    between), so a second submit cannot slip in."""
    idle(the.collection)

    async def run(handle: JobHandle) -> dict[str, object]:
        return (await index(the, handle.set_label)).model_dump()

    label = "Reading the files..."
    return get_job_runner().start(JOB + the.collection, run, label=label)


def last_job(collection: str) -> JobSnapshot | None:
    """``collection``'s newest indexing job, running or ended, if any."""
    return get_job_runner().latest(JOB + collection)


async def _forget_others(service: RAGService, collection: str, kept: set[str]) -> None:
    """Every source of ``collection`` but ``kept`` out, in one call, and
    the kept uploads among them."""
    files = await service.list_files(collection)
    gone = [f.source for f in files if f.source not in kept]
    if not gone:
        return
    await service.vectorstore.remove_by_source(collection, gone)
    if folder := kept_folder(service.config.persist_directory, collection):
        await asyncio.to_thread(forget_kept, gone, folder)
