"""Live engines, as table data.

A live call runs on an engine: a Pydantic AI realtime model that is the
agent's brain, reached on the one call path. Engines are rows, like agents
and voice profiles: seeded when missing, never overwritten once edited.
The model an engine runs on - its name, its maker, its price - is the
catalog's row.
"""

from __future__ import annotations

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.voice import live_engines, realtime_calls
from app.services.ai.domains.voice.live_engines import ENGINE_SEEDS
from app.services.ai.domains.voice.profiles import SETTINGS
from app.services.ai.models.voice import LiveEngine
from tests._voice_catalog import seed_voice_catalog


@pytest.fixture
async def seeded(async_db_session: AsyncSession) -> AsyncSession:
    await seed_voice_catalog(async_db_session)
    await live_engines.seed_missing(async_db_session)
    return async_db_session


async def _keyed(session: AsyncSession) -> dict[str, LiveEngine]:
    return {row.key: row for row in await live_engines.enabled(session)}


class TestTheRows:
    @pytest.mark.asyncio
    async def test_the_engines_on_offer(self, seeded: AsyncSession) -> None:
        assert list(await _keyed(seeded)) == [
            "gemini-live",
            "gpt-realtime-2.1",
            "gpt-realtime-2.1-mini",
            "gpt-live",
        ]
        assert live_engines.DEFAULT == "gemini-live"

    @pytest.mark.asyncio
    async def test_each_names_its_model_as_pydantic_ai_does(
        self, seeded: AsyncSession
    ) -> None:
        rows = await _keyed(seeded)
        assert live_engines.realtime_model(rows["gemini-live"]) == (
            "google:gemini-3.8-live"
        )
        assert live_engines.realtime_model(rows["gpt-live"]) == "openai:gpt-live-1"

    @pytest.mark.asyncio
    async def test_an_edit_survives_the_next_seed(self, seeded: AsyncSession) -> None:
        row = (await _keyed(seeded))["gpt-realtime-2.1"]
        row.instructions = "Be terse."
        seeded.add(row)
        await seeded.commit()

        await live_engines.seed_missing(seeded)

        stored = await seeded.exec(
            select(LiveEngine.instructions).where(LiveEngine.key == row.key)
        )
        assert stored.one() == "Be terse."


class TestHowTheyTalk:
    @pytest.mark.asyncio
    async def test_every_engine_knows_it_is_a_live_call(
        self, seeded: AsyncSession
    ) -> None:
        """The voice agent's prompt is mostly its chat prompt; spoken
        straight out, it would read lists aloud. Each engine leads with a
        live-call section, and ends the call on the tool, not a phrase."""
        for engine in (await _keyed(seeded)).values():
            assert "LIVE VOICE CALL" in (engine.instructions or "")
            assert realtime_calls.END_CALL in (engine.instructions or "")

    @pytest.mark.asyncio
    async def test_a_reply_is_capped_where_the_engine_takes_a_cap(
        self, seeded: AsyncSession
    ) -> None:
        rows = await _keyed(seeded)
        assert rows["gemini-live"].max_output_tokens
        assert rows["gpt-live"].max_output_tokens is None  # Live takes none


def test_the_active_profile_carries_its_engine() -> None:
    assert SETTINGS["live_engine"] == "VOICE_LIVE_ENGINE"


class TestResolving:
    def test_an_unknown_engine_is_the_default(self) -> None:
        rows = [LiveEngine(llm_id=0, key=seed["key"]) for seed in ENGINE_SEEDS]
        found = live_engines.pick(rows, "nope")
        assert found is not None and found.key == live_engines.DEFAULT

    @pytest.mark.asyncio
    async def test_a_model_the_catalog_lacks_waits_for_a_sync(
        self, async_db_session: AsyncSession
    ) -> None:
        assert await live_engines.seed_missing(async_db_session) == 0

    @pytest.mark.asyncio
    async def test_a_turned_off_engine_is_not_on_offer(
        self, async_db_session: AsyncSession
    ) -> None:
        await seed_voice_catalog(async_db_session)
        off = tuple(
            {**seed, "is_enabled": seed["key"] != "gpt-realtime-2.1"}
            for seed in ENGINE_SEEDS
        )
        await live_engines.seed_missing(async_db_session, off)

        found = await live_engines.resolve(async_db_session, "gpt-realtime-2.1")
        assert found is not None and found.key == live_engines.DEFAULT


class TestChoosing:
    @pytest.mark.asyncio
    async def test_a_model_picked_for_calls_gets_an_engine_that_talks_like_one(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.ai.models.llm import LargeLanguageModel, LLMOrg

        await seed_voice_catalog(async_db_session)
        google = (
            await async_db_session.exec(select(LLMOrg).where(LLMOrg.slug == "google"))
        ).one()
        async_db_session.add(
            LargeLanguageModel(
                model_id="gemini-3.1-flash-live-preview",
                title="Gemini 3.1 Flash Live",
                mode="realtime",
                served_by_org_id=google.id,
            )
        )
        await async_db_session.commit()

        made = await live_engines.choose(
            async_db_session, "gemini-3.1-flash-live-preview"
        )

        assert made is not None and made.is_enabled
        assert made.instructions == live_engines.LIVE_CALL_INSTRUCTIONS
        assert made.max_output_tokens == live_engines.REPLY_CAP

    @pytest.mark.asyncio
    async def test_a_vendor_no_call_can_reach_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.ai.models.llm import LargeLanguageModel, LLMOrg

        xai = LLMOrg(slug="xai", name="xai")
        async_db_session.add(xai)
        await async_db_session.flush()
        async_db_session.add(
            LargeLanguageModel(
                model_id="grok-voice",
                title="Grok Voice",
                mode="realtime",
                served_by_org_id=xai.id,
            )
        )
        await async_db_session.commit()

        assert await live_engines.choose(async_db_session, "grok-voice") is None
