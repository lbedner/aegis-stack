"""The Overseer AI page's RAG sections: how the index is set up and what it
holds (Knowledge: each collection, its files in the drawer, deletable),
and asking it a question (Search: ranked chunks with score and source).
File-based (Chroma), so present whenever RAG is, database or not."""

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.rag", reason="no RAG in this stack")

from app.components.web_frontend import overseer_ai_rag  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

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
    async def collections() -> list[dict[str, Any]]:
        return [
            {"name": "docs", "count": 120, "doc_count": 8},
            {"name": "code", "count": 900, "doc_count": 40},
        ]

    monkeypatch.setattr(overseer_ai_rag, "collection_stats", collections)
    monkeypatch.setattr(overseer_ai_rag, "service_status", lambda: (STATUS, []))
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


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
    async def files(name: str) -> list[Any]:
        return [SimpleNamespace(source="docs/intro.md", chunks=12)]

    monkeypatch.setattr(overseer_ai_rag, "collection_files", files)
    link = one(select(_get(client, "knowledge"), "#ai-collections tbody tr")[0], "a")
    assert "collection=docs" in link.get("href")
    html = client.get(f"{PARTIALS}/collections/docs/drawer").text
    assert "docs/intro.md" in text(one(html, "#ai-collection-files"))
    assert select(html, "button[hx-get*='confirm-delete']") or select(
        html, "[hx-get*='confirm-delete']"
    )


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
    assert select(
        client.get(f"{PARTIALS}/collections/docs/confirm-delete").text,
        "button[hx-delete]",
    )
    assert client.delete(f"{PARTIALS}/collections/docs").status_code == 204
    assert deleted == ["docs"]


def test_search_offers_each_collection(client: TestClient) -> None:
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


def test_an_empty_question_is_refused(client: TestClient) -> None:
    response = client.post(
        f"{PARTIALS}/rag/search", data={"collection": "docs", "query": " "}
    )
    assert triggers(response)["toast"]["tone"] == "error"
