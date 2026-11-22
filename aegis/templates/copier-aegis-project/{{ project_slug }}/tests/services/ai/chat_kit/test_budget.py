"""BudgetGuard — per-user daily spend against one action family."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.chat.chat_kit import BudgetGuard
from app.services.ai.domains.spend.recording import chat_action
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


async def test_one_agents_budget_counts_that_agent_alone(
    async_db_session: AsyncSession,
) -> None:
    # "chat:" is the family; one agent's action is that agent, not every
    # slug it begins (finance-analyst is not finance-analyst-deep).
    await _add_usage(async_db_session, user_id="u1", action="chat:analyst", cost=0.10)
    await _add_usage(
        async_db_session, user_id="u1", action="chat:analyst-deep", cost=5.0
    )
    status = await BudgetGuard(chat_action("analyst"), 0.25).check(
        async_db_session, "u1"
    )
    assert status.spent_usd == 0.10


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


class TestGuests:
    """Guests share one account and are told apart by session
    (``app.core.visitor``): each spends from its own ceiling, and all of
    them together from one more."""

    @staticmethod
    def _guard() -> BudgetGuard:
        return BudgetGuard(
            "chat:", 5.0, guest_session_usd=0.25, all_guests_usd=1.0
        )

    @pytest.mark.queryspy(allow_n_plus_one=True)  # two guests checked in turn
    async def test_a_guest_over_its_ceiling_is_refused_and_another_is_not(
        self, async_db_session: AsyncSession
    ) -> None:
        await _add_usage(
            async_db_session, user_id="guest:a", action="chat:x", cost=0.30
        )
        guard = self._guard()
        refused = await guard.check(async_db_session, "guest:a")
        assert refused.allowed is False
        assert refused.budget_usd == 0.25
        assert refused.shared is False
        assert (await guard.check(async_db_session, "guest:b")).allowed is True

    async def test_over_the_shared_ceiling_every_guest_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        for who in ("guest:a", "guest:b", "guest:c", "guest:d", "guest:e"):
            await _add_usage(async_db_session, user_id=who, action="chat:x", cost=0.20)
        status = await self._guard().check(async_db_session, "guest:new")
        assert status.allowed is False
        assert status.shared is True

    async def test_a_signed_in_user_keeps_their_own_budget(
        self, async_db_session: AsyncSession
    ) -> None:
        for who in ("guest:a", "guest:b", "guest:c", "guest:d", "guest:e"):
            await _add_usage(async_db_session, user_id=who, action="chat:x", cost=0.20)
        await _add_usage(async_db_session, user_id="u1", action="chat:x", cost=1.0)
        status = await self._guard().check(async_db_session, "u1")
        assert status.allowed is True
        assert status.budget_usd == 5.0
