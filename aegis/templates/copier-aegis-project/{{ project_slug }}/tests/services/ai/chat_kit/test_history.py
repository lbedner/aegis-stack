"""ConversationStore — durable single-thread-per-(surface, subject, user)."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.conversation import Conversation, ConversationMessage
from app.services.ai.domains.chat.chat_kit import ConversationStore


async def test_append_then_load_round_trips_in_order(
    async_db_session: AsyncSession,
) -> None:
    store = ConversationStore("metrics")
    await store.append_turn(
        async_db_session,
        user_id="7",
        subject_id=3,
        user_text="how are downloads?",
        assistant_text="Up 8% this week.",
    )
    tail = await store.load_tail(async_db_session, user_id="7", subject_id=3, limit=40)
    assert [(m.role, m.content) for m in tail] == [
        ("user", "how are downloads?"),
        ("assistant", "Up 8% this week."),
    ]
    # Restored turns carry a UTC timestamp (Z-marked) for the UI; the user's
    # is at or before the assistant's (strictly-increasing per-turn stamps).
    assert all(m.timestamp and m.timestamp.endswith("Z") for m in tail)
    assert tail[0].timestamp <= tail[1].timestamp


async def test_second_turn_reuses_the_same_conversation(
    async_db_session: AsyncSession,
) -> None:
    store = ConversationStore("metrics")
    for i in range(3):
        await store.append_turn(
            async_db_session,
            user_id="7",
            subject_id=3,
            user_text=f"q{i}",
            assistant_text=f"a{i}",
        )
    convs = (
        await async_db_session.exec(
            select(Conversation).where(Conversation.user_id == "7")
        )
    ).all()
    assert len(convs) == 1  # one rolling thread, not one per turn
    assert convs[0].id == "metrics:3:7"
    msgs = (await async_db_session.exec(select(ConversationMessage))).all()
    assert len(msgs) == 6  # 3 turns x (user + assistant)


async def test_load_tail_limits_and_keeps_newest(
    async_db_session: AsyncSession,
) -> None:
    store = ConversationStore("metrics")
    for i in range(5):
        await store.append_turn(
            async_db_session,
            user_id="7",
            subject_id=3,
            user_text=f"q{i}",
            assistant_text=f"a{i}",
        )
    # 10 messages total; ask for the last 4 -> the two newest turns, in order.
    tail = await store.load_tail(async_db_session, user_id="7", subject_id=3, limit=4)
    assert [m.content for m in tail] == ["q3", "a3", "q4", "a4"]


async def test_threads_are_isolated_by_subject_and_user(
    async_db_session: AsyncSession,
) -> None:
    store = ConversationStore("metrics")
    await store.append_turn(
        async_db_session, user_id="7", subject_id=3, user_text="p3", assistant_text="a"
    )
    await store.append_turn(
        async_db_session, user_id="7", subject_id=9, user_text="p9", assistant_text="a"
    )
    await store.append_turn(
        async_db_session, user_id="8", subject_id=3, user_text="u8", assistant_text="a"
    )
    only_p3 = await store.load_tail(
        async_db_session, user_id="7", subject_id=3, limit=40
    )
    assert [m.content for m in only_p3] == ["p3", "a"]


async def test_empty_thread_loads_nothing(async_db_session: AsyncSession) -> None:
    store = ConversationStore("metrics")
    tail = await store.load_tail(
        async_db_session, user_id="nobody", subject_id=1, limit=40
    )
    assert tail == []


async def test_surfaces_do_not_collide(async_db_session: AsyncSession) -> None:
    metrics = ConversationStore("metrics")
    support = ConversationStore("support")
    await metrics.append_turn(
        async_db_session, user_id="7", subject_id=3, user_text="m", assistant_text="a"
    )
    await support.append_turn(
        async_db_session, user_id="7", subject_id=3, user_text="s", assistant_text="a"
    )
    m_tail = await metrics.load_tail(
        async_db_session, user_id="7", subject_id=3, limit=40
    )
    assert [x.content for x in m_tail] == ["m", "a"]
