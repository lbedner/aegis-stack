"""Framework reference fetchers for memory modules.

Two fetchers ship with the framework: ``recent_conversations`` (a real,
useful example over the conversation tables) and ``user_profile`` (a
shape example that returns nothing - replace it with your app's actual
profile source). Importing this module registers both; app fetchers
should follow the same pattern in their own modules.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.models.conversation import Conversation

from .fetchers import FetchContext, register_fetcher

RECENT_CONVERSATION_LIMIT = 5


async def _recent_conversations_for(
    session: AsyncSession, ctx: FetchContext
) -> str | None:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == ctx.user_id)
        .order_by(col(Conversation.updated_at).desc())
        .limit(RECENT_CONVERSATION_LIMIT)
    )
    if ctx.days_back is not None:
        cutoff = datetime.now(UTC) - timedelta(days=ctx.days_back)
        stmt = stmt.where(col(Conversation.updated_at) >= cutoff)
    result = await session.exec(stmt)
    conversations = list(result.all())
    if not conversations:
        return None
    lines = "\n".join(
        f"- {conversation.title or 'Untitled conversation'}"
        for conversation in conversations
    )
    return f"Recent conversations with this user:\n{lines}"


async def recent_conversations(ctx: FetchContext) -> str | None:
    """Summarize the user's most recent conversation topics."""
    if isinstance(ctx.session, AsyncSession):
        return await _recent_conversations_for(ctx.session, ctx)
    async with get_async_session() as session:
        return await _recent_conversations_for(session, ctx)


async def user_profile(ctx: FetchContext) -> str | None:
    """Shape example: replace with your app's profile source.

    Returns None (contributes nothing) on purpose - the framework can't
    know what a "profile" is in your domain. Register a replacement with
    ``register_fetcher("user_profile", your_fetcher, replace=True)``.
    """
    return None


# Built-in registration: importing this module makes both fetchers
# referencable from memory_module.fetch_function. replace=True keeps
# re-imports idempotent.
register_fetcher(
    "recent_conversations",
    recent_conversations,
    description="Most recent conversation topics for the user",
    replace=True,
)
register_fetcher(
    "user_profile",
    user_profile,
    description="App-replaceable user profile stub",
    replace=True,
)
