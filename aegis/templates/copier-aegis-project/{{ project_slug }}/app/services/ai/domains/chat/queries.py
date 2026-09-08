"""Reads for the chat domain: conversations and their messages, agent
rows, memory modules, per-user memory, and sentiment verdicts.

``ConversationManager`` runs on a plain ``Session``; everything else on
an ``AsyncSession``. The annotation on each function says which.
Statement builders only - no business logic, no writes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.conversation import Conversation, ConversationMessage
from app.services.ai.models.agents import Agent, AgentUserMemory, MemoryModule
from app.services.ai.models.sentiment import SentimentAnalysis

# --- Conversations (sync: ConversationManager) --------------------------


def messages_for_conversation(
    session: Session, conversation_id: str
) -> Sequence[ConversationMessage]:
    return session.exec(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.timestamp)
    ).all()


def conversations_with_messages(session: Session) -> Sequence[Conversation]:
    """Every conversation, newest activity first, messages loaded in two
    queries instead of one per row."""
    return session.exec(
        select(Conversation)
        .options(selectinload(Conversation.messages))  # type: ignore[arg-type]
        .order_by(Conversation.updated_at.desc())
    ).all()


def conversation_count(session: Session) -> int:
    return session.exec(select(func.count()).select_from(Conversation)).one()


def message_count(session: Session) -> int:
    return session.exec(select(func.count()).select_from(ConversationMessage)).one()


def distinct_user_count(session: Session) -> int:
    """Distinct ``meta_data.user_id`` values, extracted in SQL on either
    engine (``->>`` on Postgres, ``json_extract`` on SQLite)."""
    user_id = Conversation.meta_data["user_id"].as_string()  # type: ignore[index]
    return session.exec(
        select(func.count(func.distinct(user_id))).where(user_id.is_not(None))
    ).one()


def conversation_ids_before(session: Session, cutoff: datetime) -> Sequence[str]:
    return session.exec(
        select(Conversation.id).where(Conversation.updated_at < cutoff)
    ).all()


# --- Conversations (async) ---------------------------------------------


async def recent_conversations_for(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int,
    since: datetime | None = None,
) -> Sequence[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(col(Conversation.updated_at).desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(col(Conversation.updated_at) >= since)
    return (await session.exec(stmt)).all()


async def recent_messages(
    session: AsyncSession, conversation_id: str, limit: int
) -> Sequence[ConversationMessage]:
    """The newest ``limit`` messages, newest first."""
    return (
        await session.exec(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(col(ConversationMessage.timestamp).desc())
            .limit(limit)
        )
    ).all()


async def latest_message_timestamp(
    session: AsyncSession, conversation_id: str
) -> datetime | None:
    return (
        await session.exec(
            select(func.max(ConversationMessage.timestamp)).where(
                ConversationMessage.conversation_id == conversation_id
            )
        )
    ).one()


async def unscored_conversations(
    session: AsyncSession, limit: int
) -> Sequence[Conversation]:
    """Oldest-first conversations with no sentiment verdict, messages
    loaded."""
    return (
        await session.exec(
            select(Conversation)
            .outerjoin(
                SentimentAnalysis,
                SentimentAnalysis.conversation_id == Conversation.id,  # type: ignore[arg-type]
            )
            .where(SentimentAnalysis.id == None)  # noqa: E711 - SQL IS NULL
            .options(selectinload(Conversation.messages))  # type: ignore[arg-type]
            .order_by(Conversation.updated_at)  # type: ignore[arg-type]
            .limit(limit)
        )
    ).all()


async def sentiment_counts(session: AsyncSession) -> Sequence[tuple[str, int]]:
    return (
        await session.exec(
            select(
                SentimentAnalysis.overall_sentiment,
                func.count(),  # type: ignore[arg-type]
            ).group_by(SentimentAnalysis.overall_sentiment)  # type: ignore[arg-type]
        )
    ).all()


async def performance_counts(session: AsyncSession) -> Sequence[tuple[str, int]]:
    return (
        await session.exec(
            select(
                SentimentAnalysis.assistant_performance,
                func.count(),  # type: ignore[arg-type]
            ).group_by(SentimentAnalysis.assistant_performance)  # type: ignore[arg-type]
        )
    ).all()


async def average_sentiment_score(session: AsyncSession) -> float | None:
    return (
        await session.exec(
            select(func.avg(SentimentAnalysis.overall_score))  # type: ignore[arg-type]
        )
    ).one_or_none()


async def recent_negative_sentiments(
    session: AsyncSession, limit: int
) -> Sequence[SentimentAnalysis]:
    return (
        await session.exec(
            select(SentimentAnalysis)
            .where(
                col(SentimentAnalysis.overall_sentiment).in_(["negative", "frustrated"])
            )
            .order_by(col(SentimentAnalysis.created_at).desc())
            .limit(limit)
        )
    ).all()


# --- Agents, memory modules, user memory (async) -----------------------


async def agent_by_slug(session: AsyncSession, slug: str) -> Agent | None:
    """The agent row with its tools loaded."""
    return (
        await session.exec(
            select(Agent).where(Agent.slug == slug).options(selectinload(Agent.tools))  # type: ignore[arg-type]
        )
    ).first()


async def all_agents(session: AsyncSession) -> Sequence[Agent]:
    """Every agent, tools loaded, ordered by slug."""
    return (
        await session.exec(
            select(Agent)
            .options(selectinload(Agent.tools))  # type: ignore[arg-type]
            .order_by(Agent.slug)  # type: ignore[arg-type]
        )
    ).all()


async def memory_module_by_slug(
    session: AsyncSession, slug: str
) -> MemoryModule | None:
    return (
        await session.exec(select(MemoryModule).where(MemoryModule.slug == slug))
    ).first()


async def memory_modules_by_priority(
    session: AsyncSession, *, active_only: bool = True
) -> Sequence[MemoryModule]:
    """Lowest priority number first - the order they render in."""
    stmt = select(MemoryModule).order_by(MemoryModule.priority)  # type: ignore[arg-type]
    if active_only:
        stmt = stmt.where(MemoryModule.is_active)
    return (await session.exec(stmt)).all()


async def memory_modules_by_slugs(
    session: AsyncSession, slugs: Iterable[str]
) -> dict[str, MemoryModule]:
    rows = (
        await session.exec(
            select(MemoryModule).where(MemoryModule.slug.in_(list(slugs)))  # type: ignore[attr-defined]
        )
    ).all()
    return {module.slug: module for module in rows}


async def user_memory_for(
    session: AsyncSession, user_id: str
) -> AgentUserMemory | None:
    return (
        await session.exec(
            select(AgentUserMemory).where(AgentUserMemory.user_id == user_id)
        )
    ).first()
