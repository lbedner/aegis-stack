"""Illiana's knowledge (the ``knowledge`` tool): what the knowledge bases
granted to the agent asking say about a question, each passage with where
it came from. An agent granted none searches nothing."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import pytest

from app.core.tools import acting_as, get_tool, load_tools
from app.services.ai.domains.chat import knowledge
from app.services.ai.domains.chat.agent_loader import default_agent_config
from app.services.rag.models import SearchResult


class _Index:
    def __init__(self) -> None:
        self.asked: list[tuple[str, list[str], int | None]] = []

    async def search_scoped(
        self, query: str, allowed_collections: Sequence[str], top_k: int | None = None
    ) -> list[SearchResult]:
        self.asked.append((query, list(allowed_collections), top_k))
        return [
            SearchResult(
                content="Refunds are issued within 14 days.",
                metadata={"source": "/docs/refunds.md"},
                score=0.82,
                rank=1,
            )
        ]


@pytest.fixture
def index(monkeypatch: pytest.MonkeyPatch) -> _Index:
    held = _Index()
    monkeypatch.setattr(knowledge, "get_rag_service", lambda: held)
    return held


def _granted(monkeypatch: pytest.MonkeyPatch, *bases: str) -> None:
    config = replace(default_agent_config(), knowledge_base_ids=bases)

    async def resolve(slug: str, **_: Any) -> Any:
        return config

    monkeypatch.setattr(knowledge, "resolve_agent", resolve)


@pytest.mark.asyncio
async def test_it_searches_the_knowledge_bases_granted_the_agent_asking(
    index: _Index, monkeypatch: pytest.MonkeyPatch
) -> None:
    _granted(monkeypatch, "default", "policies")

    with acting_as(None, "assistant"):
        found = await knowledge.knowledge("how long do refunds take?", top_k=3)

    assert index.asked == [("how long do refunds take?", ["default", "policies"], 3)]
    (passage,) = found.passages
    assert passage.source == "/docs/refunds.md"
    assert passage.text == "Refunds are issued within 14 days."
    assert passage.score == 0.82


@pytest.mark.asyncio
async def test_an_agent_granted_none_searches_nothing(
    index: _Index, monkeypatch: pytest.MonkeyPatch
) -> None:
    _granted(monkeypatch)

    found = await knowledge.knowledge("anything")

    assert index.asked == []
    assert found.passages == []
    assert found.note


def test_illiana_knows_the_default_knowledge_base() -> None:
    """What ``rag index <path>`` fills (its default collection) is what she
    knows, granted by default; a read, servable to an MCP client."""
    illiana = default_agent_config()
    load_tools()

    assert "knowledge" in illiana.tool_names
    assert illiana.knowledge_base_ids == ("default",)
    tool = get_tool("knowledge")
    assert tool is not None and tool.effect == "read"
