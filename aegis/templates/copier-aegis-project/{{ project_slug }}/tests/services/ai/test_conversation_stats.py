"""How much has been said, across every user (``conversation_stats``): the
AI health check's counts and the status route's, read on the session the
caller holds."""

import pytest

queries = pytest.importorskip(
    "app.services.ai.domains.chat.queries",
    reason="conversations are kept only by an AI persistence backend",
)

from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from app.models.conversation import Conversation, ConversationMessage  # noqa: E402
from app.services.ai.models import ConversationStats  # noqa: E402


async def test_the_counts_cover_every_user(async_db_session: AsyncSession) -> None:
    for conv_id, user in (("c1", "u1"), ("c2", "u1"), ("c3", "u2")):
        async_db_session.add(
            Conversation(id=conv_id, user_id=user, meta_data={"user_id": user})
        )
        async_db_session.add(
            ConversationMessage(conversation_id=conv_id, role="user", content="hi")
        )
    async_db_session.add(
        ConversationMessage(conversation_id="c1", role="assistant", content="hello")
    )
    await async_db_session.commit()

    stats = await queries.conversation_stats(async_db_session)

    assert stats == ConversationStats(
        total_conversations=3,
        total_messages=4,
        unique_users=2,
        average_messages_per_conversation=4 / 3,
    )
