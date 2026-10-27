"""An agent's knowledge (the ``knowledge`` tool): what the knowledge bases
granted to it (``knowledge_base_ids``) say about a question, searched when
it asks, each passage with where it came from. Illiana's is the RAG
service's default collection, what ``rag index <path>`` fills."""

from pydantic import BaseModel

from app.core.figures import FIGURES, absent
from app.core.tools import current_agent_slug, register_tool
from app.services.ai.domains.chat.agent_loader import DEFAULT_AGENT_SLUG, resolve_agent
from app.services.rag.config import get_rag_service

MOST = 20


class Passage(BaseModel):
    """A passage of a source, and how near it is to the question (0 to 1)."""

    model_config = FIGURES

    source: str
    score: float
    text: str


class Knowing(BaseModel):
    model_config = FIGURES

    passages: list[Passage]
    note: str | None = absent()


async def knowledge(question: str, top_k: int = 5) -> Knowing:
    """Search your knowledge bases: documents and code indexed for you to
    know. ``question`` in plain words; the nearest ``top_k`` passages (at
    most 20), each with its ``source`` (cite it) and a ``score`` from 0 to
    1. Use it before answering from general knowledge whenever the
    question is about this app, its business or its documents."""
    asking = current_agent_slug.get()
    # An MCP client is no agent: it reads what Illiana knows.
    if not asking or asking.startswith("mcp:"):
        asking = DEFAULT_AGENT_SLUG
    agent = await resolve_agent(asking)
    if not agent.knowledge_base_ids:
        return Knowing(passages=[], note="No knowledge base is granted to you.")
    found = await get_rag_service().search_scoped(
        question, agent.knowledge_base_ids, top_k=max(1, min(top_k, MOST))
    )
    return Knowing(
        passages=[
            Passage(
                source=str(r.metadata.get("source", "")), score=r.score, text=r.content
            )
            for r in found
        ]
    )


register_tool(
    "knowledge",
    knowledge,
    description="Search your knowledge bases for what a document says",
    effect="read",
    replace=True,
)
