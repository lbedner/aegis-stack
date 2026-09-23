"""The price lookup is memoized in the shared cache (#235).

It runs on every recorded turn and the catalog only changes when the sync
does, so asking the database each time is a query per turn for an answer
that does not move.

It first landed as a per-process dict. The sync runs in the scheduler, so
the dict it cleared was the scheduler's own: the webserver - the process
recording chat costs - kept its copy and charged the old rate until it
restarted. In the shared cache (Redis in production), a clear made by any
process is seen by all of them.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.cache import get_cache
from app.services.ai.domains.llm import queries
from app.services.ai.models.llm import LargeLanguageModel, LLMOrg, LLMPrice

KEY = f"{queries.PRICE_CACHE_PREFIX}deepseek-v4.1-flash"


@pytest.fixture(autouse=True)
async def _clean_cache() -> None:
    await queries.invalidate_price_cache()


@pytest.fixture
async def catalog(async_db_session: AsyncSession) -> None:
    org = LLMOrg(slug="deepseek", name="deepseek")
    async_db_session.add(org)
    await async_db_session.flush()
    llm = LargeLanguageModel(
        model_id="openrouter/deepseek/deepseek-v4.1-flash",
        title="V4.1 Flash",
        served_by_org_id=org.id,
    )
    async_db_session.add(llm)
    await async_db_session.flush()
    async_db_session.add(
        LLMPrice(
            llm_id=llm.id,
            org_id=org.id,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
        )
    )
    await async_db_session.flush()


def _explode_on_query(monkeypatch: pytest.MonkeyPatch, what: str) -> None:
    async def explode(*_a: object, **_k: object) -> None:
        raise AssertionError(f"asked the database twice for one {what}")

    monkeypatch.setattr(queries, "latest_price_for_model", explode)


class TestItRemembers:
    async def test_a_second_ask_does_not_query(
        self,
        async_db_session: AsyncSession,
        catalog: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        first = await queries.price_for_model(async_db_session, "deepseek-v4.1-flash")
        assert first == (1.5e-07, 6e-07)

        _explode_on_query(monkeypatch, "price")

        assert (
            await queries.price_for_model(async_db_session, "deepseek-v4.1-flash")
            == first
        )

    async def test_a_miss_is_remembered_too(
        self,
        async_db_session: AsyncSession,
        catalog: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An uncatalogued model should not cost a query on every turn
        either - and the cache's own "missing" is None, so a miss is stored
        as something else."""
        assert await queries.price_for_model(async_db_session, "not-a-model") is None

        _explode_on_query(monkeypatch, "miss")

        assert await queries.price_for_model(async_db_session, "not-a-model") is None


class TestEveryProcessSeesTheSameAnswer:
    async def test_it_lives_in_the_shared_cache(
        self, async_db_session: AsyncSession, catalog: None
    ) -> None:
        """Not in this module: a process-local copy is one no other
        process's sync can clear."""
        await queries.price_for_model(async_db_session, "deepseek-v4.1-flash")

        assert await get_cache().get(KEY) == (1.5e-07, 6e-07)
        assert not hasattr(queries, "_PRICE_CACHE")

    # The price query runs twice on purpose - once to fill the cache, once
    # after the clear - and that repeat is the behaviour under test.
    @pytest.mark.queryspy(allow_n_plus_one=True)
    async def test_a_clear_from_another_process_is_seen_here(
        self,
        async_db_session: AsyncSession,
        catalog: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The scheduler runs the sync; the webserver records the cost.
        The scheduler's clear has to reach the webserver's next lookup."""
        await queries.price_for_model(async_db_session, "deepseek-v4.1-flash")

        # The scheduler's invalidation, as the shared store sees it.
        await get_cache().invalidate_prefix(queries.PRICE_CACHE_PREFIX)

        asked: list[str] = []
        real = queries.latest_price_for_model

        async def counting(session: AsyncSession, name: str) -> LLMPrice | None:
            asked.append(name)
            return await real(session, name)

        monkeypatch.setattr(queries, "latest_price_for_model", counting)

        await queries.price_for_model(async_db_session, "deepseek-v4.1-flash")

        assert asked == ["deepseek-v4.1-flash"], "served a price the sync cleared"

    def test_the_sync_clears_it(self) -> None:
        """Wired, and awaited: an un-awaited clear is a clear that never
        happens."""
        from pathlib import Path

        source = Path("app/services/ai/domains/llm/etl/llm_sync_service.py").read_text()

        assert source.count("await invalidate_price_cache()") >= 2


class TestItHandsBackPlainValues:
    async def test_not_an_orm_row(
        self, async_db_session: AsyncSession, catalog: None
    ) -> None:
        """It crosses processes through the cache, and the caller only
        reads two floats."""
        price = await queries.price_for_model(async_db_session, "deepseek-v4.1-flash")

        assert isinstance(price, tuple)
        assert all(isinstance(value, float) for value in price)
