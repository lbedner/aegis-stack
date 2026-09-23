"""A recorded turn has to find its price.

The ledger records the name the provider answered under
("deepseek-v4.1-flash") while the catalog keys the routed id
("openrouter/deepseek/deepseek-v4.1-flash"). Matching only on equality
priced every routed call at zero, which also left the per-user daily
budget - a sum over that ledger - unable to trip.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.llm import queries
from app.services.ai.models.llm import LargeLanguageModel, LLMOrg, LLMPrice


@pytest.fixture
def session(async_db_session: AsyncSession) -> AsyncSession:
    """The root conftest's transactional session, rolled back per test."""
    return async_db_session


@pytest.fixture
async def catalog(session: AsyncSession) -> LargeLanguageModel:
    org = LLMOrg(slug="deepseek", name="deepseek")
    session.add(org)
    await session.flush()
    llm = LargeLanguageModel(
        model_id="openrouter/deepseek/deepseek-v4.1-flash",
        title="V4.1 Flash",
        served_by_org_id=org.id,
    )
    session.add(llm)
    await session.flush()
    session.add(
        LLMPrice(
            llm_id=llm.id,
            org_id=org.id,
            input_cost_per_token=1.5e-07,
            output_cost_per_token=6e-07,
        )
    )
    await session.flush()
    return llm


class TestItFindsThePrice:
    async def test_the_name_the_provider_reports(
        self, session: AsyncSession, catalog: Any
    ) -> None:
        """The bare name is what reaches ``record_usage``."""
        price = await queries.latest_price_for_model(session, "deepseek-v4.1-flash")

        assert price is not None
        assert price.input_cost_per_token == 1.5e-07

    async def test_the_routed_id_as_catalogued(
        self, session: AsyncSession, catalog: Any
    ) -> None:
        price = await queries.latest_price_for_model(
            session, "openrouter/deepseek/deepseek-v4.1-flash"
        )

        assert price is not None

    async def test_an_uncatalogued_model_still_says_nothing(
        self, session: AsyncSession, catalog: Any
    ) -> None:
        """A wrong price is worse than a missing one: the caller records
        the turn at zero and logs that it could not price it."""
        assert (await queries.latest_price_for_model(session, "not-a-model")) is None

    async def test_a_suffix_is_a_whole_segment(
        self, session: AsyncSession, catalog: Any
    ) -> None:
        """ "flash" must not match "deepseek-v4.1-flash": the separator is
        what makes the match a segment rather than a substring."""
        assert (await queries.latest_price_for_model(session, "flash")) is None
