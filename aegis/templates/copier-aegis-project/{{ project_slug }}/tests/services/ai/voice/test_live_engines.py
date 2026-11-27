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
from app.services.ai.domains.voice.profiles import SETUP
from app.services.ai.models.voice import LiveEngine
from tests._voice_catalog import seed_voice_catalog
from tests.services.ai._catalog import listed


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

    @pytest.mark.asyncio
    async def test_an_unedited_engine_takes_the_new_default(
        self, seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An engine still holding a former default was never edited, so
        the current one replaces it; an edited engine keeps its own."""
        former = "Say what you see."
        monkeypatch.setattr(
            live_engines, "FORMER_DEFAULTS", frozenset({live_engines.digest(former)})
        )
        rows = await _keyed(seeded)
        rows["gemini-live"].instructions = former
        rows["gpt-live"].instructions = "Be terse."
        seeded.add_all(rows.values())
        await seeded.commit()

        assert await live_engines.refresh_defaults(seeded) == 1

        stored = dict(
            (await seeded.exec(select(LiveEngine.key, LiveEngine.instructions))).all()
        )
        assert stored["gemini-live"] == live_engines.LIVE_CALL_INSTRUCTIONS
        assert stored["gpt-live"] == "Be terse."

    def test_the_current_default_is_not_a_former_one(self) -> None:
        assert (
            live_engines.digest(live_engines.LIVE_CALL_INSTRUCTIONS)
            not in live_engines.FORMER_DEFAULTS
        )


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
    assert SETUP["live_engine"] == "VOICE_LIVE_ENGINE"


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
        await listed(
            async_db_session,
            "grok-voice",
            served_by="xai",
            title="Grok Voice",
            mode="realtime",
        )

        assert await live_engines.choose(async_db_session, "grok-voice") is None

    @pytest.mark.asyncio
    async def test_a_local_chat_model_gets_an_engine_and_runs_as_a_cascade(
        self, async_db_session: AsyncSession
    ) -> None:
        """No realtime API: its call is the app's own chain (``cascade``),
        on the model string the call path builds."""
        await _cataloged(async_db_session, "qwen3.8:27b", "chat")

        made = await live_engines.choose(async_db_session, "qwen3.8:27b")

        assert made is not None and made.is_enabled
        await async_db_session.refresh(made, ["llm"])
        await async_db_session.refresh(made.llm, ["served_by"])
        assert live_engines.realtime_model(made) == "llamacpp:qwen3.8:27b"
        assert live_engines.chained(made)
        # A realtime seed's cap is sized for audio: a chain's reply is text.
        assert made.max_output_tokens is None

    @pytest.mark.asyncio
    async def test_a_cloud_chat_model_that_calls_tools_runs_as_a_chain_too(
        self, async_db_session: AsyncSession
    ) -> None:
        """Any vendor's, not a local one alone: the chain hears and speaks
        in the voice's own models and thinks with whatever chat model can
        call the agent's tools (2026-11-22)."""
        await _cataloged(
            async_db_session, "claude-sonnet-5", "chat", tools=True, org="anthropic"
        )

        made = await live_engines.choose(async_db_session, "claude-sonnet-5")

        assert made is not None
        await async_db_session.refresh(made, ["llm"])
        await async_db_session.refresh(made.llm, ["served_by"])
        assert live_engines.realtime_model(made) == "anthropic:claude-sonnet-5"
        assert live_engines.chained(made)

    @pytest.mark.asyncio
    async def test_a_chains_reply_is_capped_at_its_models_own_limit(
        self, async_db_session: AsyncSession
    ) -> None:
        """A realtime seed's 1200-token cap, sized for a minute of audio,
        left GPT-6 Luna no room to think: it said nothing (2026-11-22). A
        chain's cap is what the catalog says its model can write."""
        await _cataloged(
            async_db_session,
            "claude-sonnet-5",
            "chat",
            tools=True,
            org="anthropic",
            output=64_000,
        )
        await live_engines.choose(async_db_session, "claude-sonnet-5")

        engine = await live_engines.resolve(async_db_session, "claude-sonnet-5")

        assert engine is not None and live_engines.reply_cap(engine) == 64_000

    @pytest.mark.asyncio
    async def test_a_chain_the_catalog_says_nothing_of_is_not_capped(
        self, async_db_session: AsyncSession
    ) -> None:
        """A local model no sync has deployed yet: no limit to go by."""
        await _cataloged(async_db_session, "qwen3.8:27b", "chat")
        await live_engines.choose(async_db_session, "qwen3.8:27b")

        engine = await live_engines.resolve(async_db_session, "qwen3.8:27b")

        assert engine is not None and live_engines.reply_cap(engine) is None

    @pytest.mark.asyncio
    async def test_a_realtime_reply_keeps_its_engines_cap(
        self, seeded: AsyncSession
    ) -> None:
        engine = await live_engines.resolve(seeded, "gemini-live")

        assert engine is not None
        assert live_engines.reply_cap(engine) == engine.max_output_tokens
        assert engine.max_output_tokens

    def test_a_cloud_model_must_say_it_calls_tools(self) -> None:
        """Unknown is let through on a local engine (one that does not say);
        the cloud catalog says, so its silence is a no."""
        assert not live_engines.reachable("anthropic", "chat", "x", tools=None)
        assert live_engines.reachable("anthropic", "chat", "x", tools=True)

    @pytest.mark.asyncio
    async def test_a_local_model_that_does_not_chat_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        await _cataloged(async_db_session, "nomic-embed", "embedding")

        assert await live_engines.choose(async_db_session, "nomic-embed") is None

    @pytest.mark.asyncio
    async def test_a_local_model_that_cannot_call_tools_is_refused(
        self, async_db_session: AsyncSession
    ) -> None:
        """A call runs on the agent's tools: a model its engine says takes
        none cannot answer one. Unknown is let through (an engine that does
        not say)."""
        await _cataloged(async_db_session, "tiny:1b", "chat", tools=False)

        assert await live_engines.choose(async_db_session, "tiny:1b") is None
        assert live_engines.reachable("llamacpp", "chat", "x", tools=None)


async def _cataloged(
    session: AsyncSession,
    model_id: str,
    mode: str,
    tools: bool | None = None,
    org: str = "llamacpp",
    output: int | None = None,
) -> None:
    """A model ``org`` serves (llama.cpp unless named), in the catalog as
    its sync leaves it: ``tools`` said on the model by a local engine, on
    its deployment by a cloud catalog; ``output`` the deployment's output
    limit (no deployment where a cloud one says neither)."""
    from app.services.ai.models.llm import LLMDeployment
    from app.services.ai.models.provider_names import LOCAL_PROVIDERS

    local = org in LOCAL_PROVIDERS
    model = await listed(
        session,
        model_id,
        served_by=org,
        mode=mode,
        supports_tools=tools if local else None,
    )
    if output is not None or (not local and tools is not None):
        session.add(
            LLMDeployment(
                llm_id=model.id,
                org_id=model.served_by_org_id,
                output_max_tokens=output or 4096,
                function_calling=bool(tools) and not local,
            )
        )
        await session.commit()


class TestTheWait:
    @pytest.mark.asyncio
    async def test_it_is_the_median_of_a_models_recent_timed_turns(
        self, async_db_session: AsyncSession
    ) -> None:
        """What the voice dialog says a caller waits for the first word:
        the middle of the model's last turns that were timed; another
        model's, and an untimed turn (Gemini says no end of speech), aside."""
        from app.models.conversation import Conversation, ConversationMessage

        talk = Conversation(title="call", user_id="7")
        async_db_session.add(talk)
        await async_db_session.flush()
        for model, waited in (
            ("qwen3.8:27b", 1200),
            ("qwen3.8:27b", 2400),
            ("qwen3.8:27b", 1800),
            ("qwen3.8:27b", None),
            ("gemini-3.8-live", 300),
        ):
            meta: dict[str, object] = {"model": model}
            if waited is not None:
                meta["first_word_ms"] = waited
            async_db_session.add(
                ConversationMessage(
                    conversation_id=talk.id, role="assistant", meta_data=meta
                )
            )
        await async_db_session.commit()

        assert await live_engines.first_word_ms(async_db_session, "qwen3.8:27b") == 1800

    @pytest.mark.asyncio
    async def test_before_any_call_there_is_none(
        self, async_db_session: AsyncSession
    ) -> None:
        assert await live_engines.first_word_ms(async_db_session, "qwen3.8:27b") is None
