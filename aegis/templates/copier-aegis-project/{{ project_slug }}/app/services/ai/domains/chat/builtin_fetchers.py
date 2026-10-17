"""Framework reference fetchers for memory modules.

Three fetchers ship with the framework: ``recent_conversations`` (a real,
useful example over the conversation tables), ``user_profile`` (a shape
example that returns nothing - replace it with your app's actual profile
source) and ``app_map`` (what the app is, read from its code: the default
agent's). Importing this module registers them; app fetchers should
follow the same pattern in their own modules.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.ontology.summary import summary, text
from app.core.ontology.system import current
from app.services.ai.domains.chat import queries
from app.services.shared.deps import caller_is_admin

from .fetchers import FetchContext, register_fetcher

RECENT_CONVERSATION_LIMIT = 5
# The app map's fetcher, and the memory module rendering it.
APP_MAP = "app_map"


async def _recent_conversations_for(
    session: AsyncSession, ctx: FetchContext
) -> str | None:
    since = None
    if ctx.days_back is not None:
        since = datetime.now(UTC) - timedelta(days=ctx.days_back)
    conversations = await queries.recent_conversations_for(
        session, user_id=ctx.user_id, limit=RECENT_CONVERSATION_LIMIT, since=since
    )
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


async def app_map(ctx: FetchContext) -> str | None:
    """What the app is, read from its code (``ontology.summary.text``): its
    parts for an admin, its tables and the changes to them for anyone, as
    the ``ontology`` tool answers each. Built once a process."""
    model = await asyncio.to_thread(current)  # the first build reads the source
    if not await caller_is_admin():
        model = model.domain()
    return text(summary(model))


# Built-in registration: importing this module makes these fetchers
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
register_fetcher(
    APP_MAP,
    app_map,
    description="What the app is: its parts, tables and the changes to them",
    replace=True,
)
