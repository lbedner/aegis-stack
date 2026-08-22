"""BudgetGuard — per-user daily spend against one action family."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.chat.chat_kit import BudgetGuard
from app.services.ai.models.llm import LLMUsage


async def _add_usage(
    session: AsyncSession,
    *,
    user_id: str,
    action: str,
    cost: float,
    when: datetime | None = None,
) -> None:
    session.add(
        LLMUsage(
            action=action,
            model_id="claude-sonnet-5",
            user_id=user_id,
            timestamp=when or datetime.now(UTC).replace(tzinfo=None),
            input_tokens=100,
            output_tokens=50,
            total_cost=cost,
        )
    )
    await session.flush()


async def test_under_budget_allows(async_db_session: AsyncSession) -> None:
    await _add_usage(async_db_session, user_id="u1", action="chat:metrics", cost=0.05)
    status = await BudgetGuard("chat:", 0.25).check(async_db_session, "u1")
    assert status.allowed is True
    assert status.spent_usd == 0.05
    assert status.remaining_usd == 0.20


async def test_at_or_over_budget_blocks(async_db_session: AsyncSession) -> None:
    await _add_usage(async_db_session, user_id="u1", action="chat:metrics", cost=0.20)
    await _add_usage(async_db_session, user_id="u1", action="chat:metrics", cost=0.06)
    status = await BudgetGuard("chat:", 0.25).check(async_db_session, "u1")
    assert status.allowed is False
    assert status.spent_usd == 0.26
    assert status.remaining_usd == 0.0


async def test_only_this_action_family_counts(async_db_session: AsyncSession) -> None:
    # Insight spend must not eat the chat budget (and vice versa).
    await _add_usage(async_db_session, user_id="u1", action="insight:weekly", cost=5.0)
    await _add_usage(async_db_session, user_id="u1", action="chat:metrics", cost=0.10)
    status = await BudgetGuard("chat:", 0.25).check(async_db_session, "u1")
    assert status.spent_usd == 0.10
    assert status.allowed is True


async def test_only_this_user_counts(async_db_session: AsyncSession) -> None:
    await _add_usage(async_db_session, user_id="other", action="chat:metrics", cost=9.0)
    await _add_usage(async_db_session, user_id="u1", action="chat:metrics", cost=0.10)
    status = await BudgetGuard("chat:", 0.25).check(async_db_session, "u1")
    assert status.spent_usd == 0.10


async def test_yesterdays_spend_does_not_count(async_db_session: AsyncSession) -> None:
    yesterday = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    await _add_usage(
        async_db_session,
        user_id="u1",
        action="chat:metrics",
        cost=9.0,
        when=yesterday,
    )
    status = await BudgetGuard("chat:", 0.25).check(async_db_session, "u1")
    assert status.spent_usd == 0.0
    assert status.allowed is True


async def test_no_history_allows(async_db_session: AsyncSession) -> None:
    status = await BudgetGuard("chat:", 0.25).check(async_db_session, "fresh-user")
    assert status.allowed is True
    assert status.spent_usd == 0.0


async def test_fails_open_on_unreadable_ledger() -> None:
    class _BrokenSession:
        async def exec(self, *args, **kwargs):
            raise RuntimeError("db down")

    status = await BudgetGuard("chat:", 0.25).check(_BrokenSession(), "u1")
    assert status.allowed is True  # never block a turn on a read error
    assert status.degraded is True
