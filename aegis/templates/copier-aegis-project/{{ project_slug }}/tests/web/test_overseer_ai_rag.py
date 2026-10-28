"""The Overseer AI page's RAG sections: how the index is set up and what it
holds (Knowledge: each collection, its files in the drawer, a new one made
with parts of the app ticked, known by their code (the twin's map, no path
typed), and files uploaded; a source removed, all re-indexed, the
collection deleted), and asking it a question (Search: ranked chunks with
score and source). Read through the RAG service, so present whenever RAG
is, database or not."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.rag", reason="no RAG in this stack")

from app.components.web_frontend import overseer_ai_rag  # noqa: E402
from app.services.rag import knowable, sources  # noqa: E402
from app.services.rag.knowable import Knowable  # noqa: E402
from app.services.rag.models import (  # noqa: E402
    CollectionInfo,
    FileIndexResult,
    IndexedFile,
)
from app.services.rag.uploads import PATTERN  # noqa: E402
from app.services.system.jobs import JobSnapshot  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.services.rag.fakes import FakeIndex, index_fixture  # noqa: E402, F401
from tests.web.dom import (  # noqa: E402
    checked,
    location,
    one,
    select,
    table_rows,
    text,
    triggers,
)
from tests.web.overseer import sign_in, status_with  # noqa: E402

# What the twin offers, and each pick's files of a type (a folder, to the
# fake index): what ``rag.knowable`` hands the form, and reads for a pick.
KNOWABLE = Knowable(
    parts=[
        ("Services", [("service:ai", "ai", "AI")]),
        ("Docs", [("docs", "docs", "The documentation")]),
    ],
    types=[("Code", [".py"]), ("Docs", [".md"])],
    held={"service:ai": {".py": (188, 984_064)}, "docs": {".md": (12, 40_960)}},
    ticked=[".py"],
)
CODE = {"service:ai": "/code/app/services/ai", "docs": "/code/docs", "x": "/gone"}


def _read(
    picked: list[str], extensions: list[str], exclude: list[str] | None = None
) -> list[str]:
    assert extensions, "a pick is read for the types ticked"
    return [CODE[p] for p in picked]


PAGE = "/overseer/services/ai"
PARTIALS = "/partials/overseer/ai"
STATUS: dict[str, Any] = {
    "enabled": True,
    "persist_directory": "./data/chromadb",
    "embedding_provider": "sentence-transformers",
    "embedding_model": "all-MiniLM-L6-v2",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "default_top_k": 5,
    "last_activity": None,
}


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def collections() -> list[CollectionInfo]:
        return [
            CollectionInfo(name="docs", count=120, doc_count=8),
            CollectionInfo(name="code", count=900, doc_count=40),
        ]

    monkeypatch.setattr(overseer_ai_rag, "collection_stats", collections)

    async def names() -> list[str]:
        return ["docs", "code"]

    monkeypatch.setattr(overseer_ai_rag, "collection_names", names)

    async def no_files(name: str) -> list[IndexedFile]:
        return []

    monkeypatch.setattr(overseer_ai_rag, "collection_files", no_files)
    monkeypatch.setattr(overseer_ai_rag, "service_status", lambda: (STATUS, []))
    monkeypatch.setattr(knowable, "knowable", lambda: KNOWABLE)
    monkeypatch.setattr(knowable, "paths_of", _read)
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


def _started(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """``start_adding`` recorded, not run: what each submit asked for."""
    asked: list[tuple[Any, ...]] = []

    async def start(*given: Any) -> str:
        asked.append(given)
        return "job-1"

    monkeypatch.setattr(overseer_ai_rag, "start_adding", start)
    return asked


def _steps(html: Any) -> list[str]:
    """A wizard's steps, in order, by title."""
    steps = select(html, "[data-wizard-steps] li")
    return [text(one(step, "[data-step-title]")) for step in steps]


def _get(client: TestClient, section: str, query: str = "") -> str:
    response = client.get(f"{PAGE}/{section}" + (f"?{query}" if query else ""))
    assert response.status_code == 200, response.text
    return response.text


def test_knowledge_shows_the_index_and_its_collections(client: TestClient) -> None:
    html = _get(client, "knowledge")
    rows = [text(r) for r in select(html, "#ai-collections tbody tr")]
    assert "docs" in rows[0] and "120" in rows[0] and "8" in rows[0]
    assert "all-MiniLM-L6-v2" in text(one(html, "#ai-rag-setup"))
    figures = {
        text(one(c, "dt")): text(select(c, "dd")[0])
        for c in select(html, "#ai-rag-figures > div")
    }
    assert figures["Collections"] == "2" and figures["Chunks"] == "1,020"


def test_a_collection_opens_with_its_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each file with its type, chunks and when it was indexed, removable;
    a source to add, and the whole collection to re-index or delete."""

    async def files(name: str) -> list[IndexedFile]:
        return [
            IndexedFile(
                source="/srv/docs/intro.md",
                chunks=12,
                indexed_at=datetime(2026, 10, 1, 9),
                content_type="markdown",
            )
        ]

    monkeypatch.setattr(overseer_ai_rag, "collection_files", files)
    code = "/overseer/code?file=docs%2Fintro.md"
    monkeypatch.setattr(overseer_ai_rag, "file_url", lambda path: code)
    link = one(select(_get(client, "knowledge"), "#ai-collections tbody tr")[0], "a")
    assert "collection=docs" in link.get("href")
    html = client.get(f"{PARTIALS}/collections/docs/drawer").text
    # Room for the files' columns: the drawer widens for it.
    assert select(html, "[data-wide]")
    [row] = table_rows(html, "#ai-collection-files table")
    assert [text(row[c]) for c in ("Source", "Type", "Indexed")] == [
        "/srv/docs/intro.md",
        "markdown",
        "Oct 1",
    ]
    # The source opens in Overseer > Code, beside the icon of its type.
    assert one(row["Source"], "a").get("href") == code
    assert one(row["Source"], "[data-file-type]").get("data-file-type") == "markdown"
    # Its options behind one button: open it, read it again, remove it.
    menu = one(html, "#ai-collection-files details[data-dropdown]")
    assert text(one(menu, "a")) == "Open in Code" and one(menu, "a").get("href") == code
    again = one(menu, "[hx-post*='/reindex']")
    assert text(again) == "Re-index"
    assert "source=%2Fsrv%2Fdocs%2Fintro.md" in again.get("hx-post")
    remove = one(menu, "[hx-get*='/sources/remove']")
    assert "source=%2Fsrv%2Fdocs%2Fintro.md" in remove.get("hx-get")
    # Adding opens the steps in the dialog, for this collection: no Name.
    add = one(html, "[hx-get$='/collections/docs/add']")
    assert text(add) == "Add sources"
    adding = client.get(f"{PARTIALS}/collections/docs/add").text
    assert one(adding, "input[name=collection]").get("value") == "docs"
    assert _steps(adding) == ["Source code", "File types", "Files", "Review"]
    # Re-indexing and deleting it stay out of sight behind "...".
    actions = one(html, "#ai-collection-actions")
    assert [text(b) for b in select(actions, ":scope > button")] == ["Add sources"]
    more = one(actions, "details[data-dropdown]")
    assert text(one(more, "[hx-post$='/collections/docs/reindex']")) == "Re-index"
    assert text(one(more, "[hx-get*='confirm-delete']")) == "Delete collection"


def test_a_collection_that_is_not_there_is_a_404(client: TestClient) -> None:
    """A drawer for a name the index does not hold (a stale link): no such
    collection, not a crash."""
    assert client.get(f"{PARTIALS}/collections/gone/drawer").status_code == 404


def test_a_collection_is_deleted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted: list[str] = []

    async def delete(name: str) -> bool:
        deleted.append(name)
        return True

    monkeypatch.setattr(overseer_ai_rag, "delete_collection", delete)
    button = one(
        client.get(f"{PARTIALS}/collections/docs/confirm-delete").text,
        "button[hx-delete]",
    )
    assert button.get("data-api-done") == "Collection deleted"  # whole, unquoted
    assert client.delete(f"{PARTIALS}/collections/docs").status_code == 204
    assert deleted == ["docs"]

    # Not while it is being indexed: its next batch would make it again.
    running = SimpleNamespace(status="running", label="Indexing 1 of 9 files...")
    monkeypatch.setattr(sources, "last_job", lambda name: running)
    busy = client.delete(f"{PARTIALS}/collections/docs")
    assert busy.status_code == 409 and "being indexed" in busy.json()["detail"]
    assert deleted == ["docs"]


def test_a_knowledge_base_is_made_with_its_first_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert select(_get(client, "knowledge"), "[hx-get$='/collections/new']")
    form = one(client.get(f"{PARTIALS}/collections/new").text, "form")
    assert form.get("hx-post") == f"{PARTIALS}/sources"
    assert form.get("data-wide") is not None  # room for the picks
    # One step at a time: Name, the parts, their file types, files, review;
    # each step's answer beside it once passed (an Alpine expression).
    assert _steps(form) == ["Name", "Source code", "File types", "Files", "Review"]
    name, code, kinds, files, review = select(form, "[data-wizard-step]")
    named = one(name, "input[name=collection]")
    assert named.get("required") is not None
    # What the index takes as a name, said under it once typed otherwise;
    # Enter in a step walks on, as Next does, never submitting early.
    assert named.get("pattern") == PATTERN  # the server's own rule
    assert "no spaces" in text(one(name, "[data-invalid]"))
    assert one(form, "[data-wizard]").get("@keydown.enter") == "enter($event)"
    assert all(s.get("x-cloak") is not None for s in (code, kinds, files, review))
    # Every part ticked from the start, each kind of part flipped at once.
    assert [text(g) for g in select(code, "p.caps")] == ["Services", "Docs"]
    assert checked(code, "input[name=part]") == ["service:ai", "docs"]
    assert len(select(code, "[data-all-parts]")) == len(KNOWABLE.parts)
    # Whose code, and from where: never a doubt which folder that is.
    root = text(one(code, "[data-root]"))
    assert KNOWABLE.app in root and KNOWABLE.root in root
    # The types the parts hold, the loader's own ticked; all or none at once.
    types = [i.get("value") for i in select(kinds, "[data-file-types] input")]
    assert types == [".py", ".md"]
    assert checked(kinds, "[data-file-types] input") == [".py"]
    assert select(kinds, "[data-all-types]")
    # Files pile up across picks, listed, of a type the loader reads.
    picker = one(files, "[data-file-picker]")
    assert one(picker, "input[type=file]").get("accept") == ",".join(KNOWABLE.readable)
    # The review says it all, and how much: each pick's files by type.
    assert select(review, "[data-review]") and select(review, "[data-total]")
    assert '"service:ai": {".py": [188, 984064]}' in form.get("x-data")
    footer = select(form, "[data-wizard-back]")[0].getparent()
    assert "justify-end" in footer.get("class")
    assert select(footer, "[data-wizard-next] button")
    assert text(one(footer, "[data-wizard-submit] button")) == "Make knowledge base"

    started = _started(monkeypatch)

    response = client.post(
        f"{PARTIALS}/sources",
        data={"collection": "policies", "part": "service:ai", "extension": ".py"},
        files=[("file", ("refunds.md", b"14 days")), ("file", ("returns.md", b"x"))],
    )

    # Indexed in the background: the dialog closes, the collection opens.
    uploads = [("refunds.md", b"14 days"), ("returns.md", b"x")]
    assert started == [("policies", uploads, ["service:ai"], [".py"])]
    assert "collection=policies" in location(response)
    assert triggers(response)["toast"]["text"] == "Indexing policies..."


@pytest.mark.parametrize(
    ("worker", "provider", "slow"),
    [
        (False, "sentence-transformers", True),
        (True, "sentence-transformers", False),
        (False, "openai", False),
    ],
)
def test_the_review_says_when_indexing_will_be_slow(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    worker: bool,
    provider: str,
    slow: bool,
) -> None:
    """Embedding on this server's CPU, with no worker to spread it over:
    what would make it faster, said before it starts."""
    from app.services.rag import embedding

    monkeypatch.setattr(embedding, "workers", lambda: worker)
    config = SimpleNamespace(chunk_size=1000, embedding_provider=provider)
    monkeypatch.setattr(
        overseer_ai_rag, "_service", lambda: SimpleNamespace(config=config)
    )

    form = one(client.get(f"{PARTIALS}/collections/new").text, "form")

    review = select(form, "[data-wizard-step]")[-1]
    assert bool(select(review, "[data-slow]")) is slow


def test_a_picker_left_empty_sends_no_upload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It still sends its field, as an empty string."""
    started = _started(monkeypatch)

    client.post(
        f"{PARTIALS}/sources",
        data={"collection": "docs", "part": ["service:ai", "docs"], "extension": ".md"},
        files={"file": ("", b"", "application/octet-stream")},
    )

    assert started == [("docs", [], ["service:ai", "docs"], [".md"])]


def test_what_cannot_be_added_is_said_at_once(
    client: TestClient, index: FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal is the error toast, before any job; the index failing too."""
    nothing = client.post(f"{PARTIALS}/sources", data={"collection": "docs"})

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Collection code does not exist.")

    monkeypatch.setattr(overseer_ai_rag, "start_adding", broken)
    failing = client.post(f"{PARTIALS}/sources", data={"collection": "code"})

    assert triggers(nothing)["toast"]["tone"] == "error"
    toast = triggers(failing)["toast"]
    assert toast["tone"] == "error" and "does not exist" in toast["text"]


def test_a_running_job_is_followed_on_the_drawer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pushed as it changes (SSE), nothing polled; a collection still being
    made, not yet in the index, opens too."""
    job = JobSnapshot(
        job_id="j1",
        name="rag-sources:fresh",
        status="running",
        label="Indexing 50 of 200 files...",
        result=None,
        error=None,
    )

    def last_job(collection: str) -> JobSnapshot:
        return job

    monkeypatch.setattr(overseer_ai_rag, "last_job", last_job)

    html = client.get(f"{PARTIALS}/collections/fresh/drawer").text

    stream = one(html, "#ai-collection-job [sse-connect]")
    assert stream.get("sse-connect").endswith("/collections/fresh/jobs/j1/events")
    assert stream.get("sse-close") == overseer_ai_rag.JOB_DONE
    assert one(stream, "progress").get("value") == "0.25"
    assert not select(html, "[hx-trigger*='every']")  # never polled


def test_how_a_job_ended_is_said() -> None:
    def ended(status: str, **left: Any) -> dict[str, Any]:
        job = {"job_id": "j", "status": status, "label": ""}
        return job | {"result": None, "error": None} | left

    some = overseer_ai_rag.job_view(
        "docs", ended("done", result={"files": 2, "chunks": 9, "unread": ["a.bin"]})
    )
    broke = overseer_ai_rag.job_view("docs", ended("failed", error="Unreadable"))

    clean = overseer_ai_rag.job_view(
        "docs", ended("done", result={"files": 1200, "chunks": 4728, "unread": []})
    )
    running = overseer_ai_rag.job_view("docs", ended("running", label="Reading"))

    # Its card says where it stands: going, done, or failed.
    assert (running["title"], clean["title"], broke["title"]) == (
        "Indexing",
        "Done",
        "Failed",
    )
    assert clean["label"] == "1,200 files, 4,728 chunks."
    assert some["tone"] == "warn"
    assert "2 files" in some["label"] and "a.bin" in some["label"]
    assert broke["tone"] == "error" and broke["label"] == "Unreadable"


@pytest.mark.asyncio
async def test_the_job_is_pushed_until_it_ends() -> None:
    """Each change pushed, then the end: the stream closed, the drawer
    loaded once more so its files are the new ones."""
    from app.services.system.jobs import get_job_runner

    go = asyncio.Event()

    async def work(handle: Any) -> dict[str, Any]:
        handle.set_label("Indexing 1 of 2 files...")
        await go.wait()
        return {"files": 2, "chunks": 4, "unread": []}

    job_id = get_job_runner().start("rag-sources:docs", work, label="Reading...")
    frames: list[str] = []
    async for sent in overseer_ai_rag.job_events("docs", job_id):
        frames.append(sent)
        go.set()

    assert frames[0].startswith(f"event: {overseer_ai_rag.JOB_EVENT}")
    assert any("2 files" in f for f in frames)
    assert "/collections/docs/drawer" in frames[-2]
    assert frames[-1].startswith(f"event: {overseer_ai_rag.JOB_DONE}")


def test_a_source_is_removed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[tuple[str, str]] = []

    async def remove(collection: str, source: str) -> FileIndexResult:
        removed.append((collection, source))
        return FileIndexResult(
            file_path=source, file_hash="h", chunk_count=3, action="removed"
        )

    monkeypatch.setattr(overseer_ai_rag, "remove_source", remove)
    confirm = client.get(
        f"{PARTIALS}/collections/docs/sources/remove",
        params={"source": "/srv/docs/a.md"},
    ).text
    assert "source=%2Fsrv%2Fdocs%2Fa.md" in one(confirm, "button[hx-delete]").get(
        "hx-delete"
    )

    response = client.delete(
        f"{PARTIALS}/collections/docs/sources", params={"source": "/srv/docs/a.md"}
    )

    assert response.status_code == 204
    assert removed == [("docs", "/srv/docs/a.md")]


def test_a_collection_is_read_again(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the background too: its drawer follows it."""
    started: list[tuple[str, str | None]] = []

    async def start(collection: str, source: str | None = None) -> str:
        started.append((collection, source))
        return "job-2"

    monkeypatch.setattr(overseer_ai_rag, "start_reindex", start)

    response = client.post(f"{PARTIALS}/collections/docs/reindex")
    one_file = client.post(
        f"{PARTIALS}/collections/docs/reindex", params={"source": "/srv/a.md"}
    )

    assert started == [("docs", None), ("docs", "/srv/a.md")]
    assert "collection=docs" in location(response)
    assert "collection=docs" in location(one_file)


def test_search_offers_each_collection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By name alone: counting each collection's files reads every chunk."""

    async def counted() -> None:
        raise AssertionError("the search page counted every collection")

    monkeypatch.setattr(overseer_ai_rag, "collection_stats", counted)
    options = [
        o.get("value")
        for o in select(
            _get(client, "search"), "#ai-rag-search select[name=collection] option"
        )
    ]
    assert options == ["docs", "code"]


def test_a_search_returns_ranked_chunks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[dict[str, Any]] = []

    async def search(**kwargs: Any) -> list[Any]:
        asked.append(kwargs)
        return [
            SimpleNamespace(
                rank=1,
                score=0.91,
                content="Aegis is a stack.",
                metadata={"source": "docs/intro.md"},
            )
        ]

    monkeypatch.setattr(overseer_ai_rag, "search", search)
    code = "/overseer/code?file=docs%2Fintro.md"
    monkeypatch.setattr(overseer_ai_rag, "file_url", lambda path: code)
    response = client.post(
        f"{PARTIALS}/rag/search",
        data={"collection": "docs", "query": "what is aegis", "top_k": "3"},
    )
    assert response.status_code == 200, response.text
    assert asked == [{"query": "what is aegis", "collection_name": "docs", "top_k": 3}]
    result = text(one(response.text, "#ai-rag-results"))
    assert (
        "Aegis is a stack." in result and "docs/intro.md" in result and "0.91" in result
    )
    # Its source as the drawer shows it: its type's icon, opening in Code.
    [row] = table_rows(response.text, "#ai-rag-results table")
    assert one(row["Source"], "a").get("href") == code
    assert one(row["Source"], "[data-file-type]").get("data-file-type") == "markdown"


def test_an_empty_question_is_refused(client: TestClient) -> None:
    response = client.post(
        f"{PARTIALS}/rag/search", data={"collection": "docs", "query": " "}
    )
    assert triggers(response)["toast"]["tone"] == "error"
