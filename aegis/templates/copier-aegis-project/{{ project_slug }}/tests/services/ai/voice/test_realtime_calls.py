"""A live call: one path for every engine.

The agent is the brain: prompt, tools, code mode. The server sees every
event; each finished turn is saved into the conversation the way a typed
turn is (what was heard, what was said, the steps taken), and the call's
priced usage goes to the ledger.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
    RealtimeTurnCompleteEvent,
    SpeechPart,
    ToolCallPart,
    ToolReturnPart,
)
import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.api.ai.service import ai_service
from app.services.ai import usage_recording
from app.services.ai.domains.voice.realtime_calls import (
    CALL_TOOLS,
    END_CALL,
    RESUME_WINDOW,
    TurnLog,
    resumed,
    save_turn,
)
from app.services.ai.models import AIProvider
from app.services.ai.models.llm import LLMUsage
from tests._session import opens
from tests._voice_catalog import seed_voice_catalog

USER = "7"


def _turn() -> list[object]:
    call = ToolCallPart(
        tool_name="run_code", args={"code": "await budget()"}, tool_call_id="t1"
    )
    result = ToolReturnPart(
        tool_name="run_code", content="{'net': -19939}", tool_call_id="t1"
    )
    return [
        PartEndEvent(
            index=0, part=SpeechPart(speaker="user", transcript="How much is left?")
        ),
        FunctionToolCallEvent(part=call),
        FunctionToolResultEvent(part=result),
        PartEndEvent(
            index=1,
            part=SpeechPart(speaker="assistant", transcript="You're $199.39 over."),
        ),
        RealtimeTurnCompleteEvent(),
    ]


async def _conversation(
    provider: AIProvider = AIProvider.GOOGLE, model: str = "gemini-3.8-live"
) -> Any:
    return await ai_service.conversation_manager.create_conversation(
        provider=provider, model=model, user_id=USER, surface="app"
    )


async def _priced(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """What a driven call is priced against: the voice catalog, and the
    usage ledger on the test's session."""
    monkeypatch.setattr(usage_recording, "get_async_session", opens(session))
    await seed_voice_catalog(session)


class TestATurn:
    def test_a_turn_is_what_you_said_what_she_said_and_her_steps(self) -> None:
        log = TurnLog()
        done = [log.observe(event) for event in _turn()]
        assert done == [False, False, False, False, True]
        turn = log.take()
        assert turn is not None
        heard, said, trace = turn
        assert (heard, said) == ("How much is left?", "You're $199.39 over.")
        assert [step["tool"] for step in trace] == ["run_code"]
        assert trace[0]["code"] == "await budget()"
        assert log.take() is None  # taken once

    def test_a_part_ended_twice_is_said_once(self) -> None:
        """#292: one reply was saved with its text twice, back to back - the
        same spoken part reported finished twice."""
        events = _turn()
        log = TurnLog()
        for event in [*events[:-1], events[-2], events[-1]]:
            log.observe(event)
        turn = log.take()

        assert turn is not None
        assert turn[1] == "You're $199.39 over."

    @pytest.mark.asyncio
    async def test_a_finished_turn_lands_in_the_conversation(self) -> None:
        conversation = await _conversation(AIProvider.OPENAI, "gpt-realtime-2.1")
        log = TurnLog()
        for event in _turn():
            log.observe(event)
        turn = log.take()
        assert turn is not None
        heard, said, trace = turn

        await save_turn(
            ai_service,
            conversation.id,
            heard,
            said,
            trace,
            model="gpt-realtime-2.1",
            provider="openai",
        )

        stored = await ai_service.get_conversation(conversation.id)
        user, reply = stored.messages[-2:]
        assert user.content == "How much is left?"
        assert reply.content == "You're $199.39 over."
        assert reply.metadata["tool_trace"][0]["tool"] == "run_code"
        assert reply.metadata["model"] == "gpt-realtime-2.1"


class TestHangingUp:
    """Every realtime call can end itself: a phrase to listen for is one
    the model can drop (Gemini said "Have a great day!"), a tool is not."""

    def test_every_call_carries_the_end_call_tool(self) -> None:
        tool = CALL_TOOLS.tools[END_CALL]
        assert "goodbye" in (tool.description or "")

    def test_ending_the_call_is_not_one_of_her_steps(self) -> None:
        log = TurnLog()
        part = ToolCallPart(tool_name=END_CALL, args={}, tool_call_id="e1")
        for event in (
            PartEndEvent(index=0, part=SpeechPart(speaker="user", transcript="Bye")),
            FunctionToolCallEvent(part=part),
            FunctionToolResultEvent(
                part=ToolReturnPart(tool_name=END_CALL, content="ok", tool_call_id="e1")
            ),
            RealtimeTurnCompleteEvent(),
        ):
            log.observe(event)
        turn = log.take()
        assert turn is not None and turn[2] == []


class TestACallKnowsWhoSheIs:
    """A realtime session sends the agent's INSTRUCTIONS, never its
    system_prompt - and her whole prompt is the system prompt. Every live
    call reached the model with the history and the tool list alone: no
    call manners, no change types (she said she could not change a payee,
    2026-10-01), no sandbox rules (she called propose inside run_code)."""

    @pytest.mark.asyncio
    async def test_her_prompt_leads_then_the_conversation(self) -> None:
        from pydantic_ai import Agent

        from app.services.ai.domains.voice.realtime_calls import call_instructions

        agent = Agent(
            "test", system_prompt="You are Illiana. `transaction.assign_payee`"
        )
        said = await call_instructions(agent, "User: hi\nAssistant: hello")

        assert said.startswith("You are Illiana.")
        assert "`transaction.assign_payee`" in said
        assert said.index("You are Illiana.") < said.index("User: hi")

    @pytest.mark.asyncio
    async def test_a_first_call_is_her_prompt_alone(self) -> None:
        from pydantic_ai import Agent

        from app.services.ai.domains.voice.realtime_calls import call_instructions

        assert await call_instructions(Agent("test", system_prompt="P"), "") == "P"


class TestACallRemembers:
    """A call opens on a thread that ends with HER last reply - the one
    before it ended there - and the history builder assumed the last
    message was a question being asked now: it set it aside and returned
    nothing unless it was yours. Every call started blank ("I can't see
    our previous conversation", 2026-09-30)."""

    def test_a_call_opens_with_the_thread_so_far(self) -> None:
        from app.services.ai.models import Conversation, MessageRole
        from app.services.ai.service.prompt import PromptMixin

        conversation = Conversation(
            id="c1", provider=AIProvider.GOOGLE, model="gemini-3.8-live"
        )
        conversation.add_message(MessageRole.USER, "You should see a $1,500 charge.")
        conversation.add_message(
            MessageRole.ASSISTANT, "Blondin Endodontics, $1,500, on your AMEX."
        )

        history = PromptMixin._build_conversation_context(  # type: ignore[arg-type]
            None, conversation
        )

        assert "User: You should see a $1,500 charge." in history
        assert history.rstrip().endswith(
            "Assistant: Blondin Endodontics, $1,500, on your AMEX."
        )

    def test_a_typed_turn_still_ends_on_the_question(self) -> None:
        from app.services.ai.models import Conversation, MessageRole
        from app.services.ai.service.prompt import PromptMixin

        conversation = Conversation(id="c2", provider=AIProvider.OPENAI, model="m")
        conversation.add_message(MessageRole.USER, "Hi")
        conversation.add_message(MessageRole.ASSISTANT, "Hello")
        conversation.add_message(MessageRole.USER, "And now?")

        history = PromptMixin._build_conversation_context(  # type: ignore[arg-type]
            None, conversation
        )

        assert history.endswith("\n\nUser: And now?")
        assert history.count("And now?") == 1


class TestACutCall:
    """A call can drop mid-answer (a restart, the network, a hang-up). What
    was said and run so far is kept, marked, and a call soon after picks
    up where it stopped."""

    @pytest.mark.asyncio
    async def test_a_turn_cut_off_is_kept_and_marked(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from app.services.ai.domains.voice.realtime_calls import drive
        from tests._realtime import FakeRealtime

        await _priced(async_db_session, monkeypatch)
        conversation = await _conversation()
        realtime = FakeRealtime(_turn()[:2])  # you asked; she started working

        async def hang_up(session: object) -> None:
            await asyncio.sleep(0.05)
            await session.close()  # type: ignore[attr-defined]

        await drive(
            ai_service,
            realtime,
            conversation_id=conversation.id,
            model="google:gemini-3.8-live",
            agent_slug="voice",
            user_id=USER,
            alongside=hang_up,
        )

        stored = await ai_service.get_conversation(conversation.id)
        user, reply = stored.messages[-2:]
        assert user.content == "How much is left?"
        assert reply.metadata["interrupted"] is True
        assert [step["tool"] for step in reply.metadata["tool_trace"]] == ["run_code"]

    @pytest.mark.asyncio
    async def test_a_call_soon_after_picks_up_the_question(self) -> None:
        from datetime import UTC, datetime

        conversation = await _conversation()
        await save_turn(
            ai_service,
            conversation.id,
            "How much is left?",
            "",
            [],
            model="gemini-3.8-live",
            provider="google",
            interrupted=True,
        )
        stored = await ai_service.get_conversation(conversation.id)
        at = stored.messages[-1].timestamp
        at = at if at.tzinfo else at.replace(tzinfo=UTC)

        assert resumed(stored, now=at) == "How much is left?"
        # after the window it is a new call, not a dropped one
        assert resumed(stored, now=at + RESUME_WINDOW * 2) is None
        assert resumed(stored, now=datetime.now(UTC) + RESUME_WINDOW * 2) is None

    @pytest.mark.asyncio
    async def test_a_finished_turn_is_not_picked_up(self) -> None:
        conversation = await _conversation()
        await save_turn(
            ai_service,
            conversation.id,
            "How much is left?",
            "You're $199.39 over.",
            [],
            model="gemini-3.8-live",
            provider="google",
        )
        stored = await ai_service.get_conversation(conversation.id)
        assert resumed(stored) is None


class TestTheLedger:
    @pytest.mark.asyncio
    async def test_the_call_is_priced_from_its_usage(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """At the catalog's rates: text, audio and cached input each at its
        own, then text and audio output (Pydantic AI's totals include the
        audio and the cached share)."""
        await _priced(async_db_session, monkeypatch)
        usage = SimpleNamespace(
            input_tokens=15_299,
            input_audio_tokens=1_000,
            cache_read_tokens=12_000,
            cache_audio_read_tokens=0,
            output_tokens=887,
            output_audio_tokens=600,
            tool_calls=2,
        )

        await usage_recording.record_realtime(
            "gpt-realtime-2.1",
            usage,
            seconds=49.9,
            conversation_id="c-1",
            rates=await usage_recording.realtime_price("gpt-realtime-2.1"),
        )

        (row,) = (await async_db_session.exec(select(LLMUsage))).all()
        assert (row.action, row.model_id, row.conversation_id) == (
            "realtime",
            "gpt-realtime-2.1",
            "c-1",
        )
        text_in, audio_in, cached = 2_299 * 4e-6, 1_000 * 32e-6, 12_000 * 0.4e-6
        text_out, audio_out = 287 * 24e-6, 600 * 64e-6
        assert row.total_cost == pytest.approx(
            text_in + audio_in + cached + text_out + audio_out
        )
        assert (row.input_tokens, row.output_tokens, row.tool_calls) == (15_299, 887, 2)
        assert row.audio_seconds == pytest.approx(49.9)


class TestTheSettings:
    """Each provider's session settings, from one place."""

    def test_openai_speaks_her_voice_and_transcribes_what_you_said(self) -> None:
        from app.services.ai.domains.voice.realtime_calls import (
            INPUT_TRANSCRIPTION,
            _model_settings,
        )

        assert _model_settings("openai:gpt-realtime-2.1", "cedar", 1200) == {
            "openai_voice": "cedar",
            "input_transcription_model": INPUT_TRANSCRIPTION,
            "max_tokens": 1200,
        }

    def test_gemini_keeps_its_own_voice_and_transcription(self) -> None:
        """Gemini transcribes by default and has no OpenAI voices; sending
        OpenAI's settings would name a voice it does not have."""
        from app.services.ai.domains.voice.realtime_calls import _model_settings

        assert _model_settings("google:gemini-3.8-live", "cedar", 1200) == {
            "max_tokens": 1200,
            "google_vad": {"start_sensitivity": "low", "end_sensitivity": "high"},
        }

    def test_gpt_live_through_pydantic_ai_is_told_how_to_speak(self) -> None:
        """#274's trial: GPT-Live run by Pydantic AI. Its voice model takes
        the call manners as its own instructions (her agent's prompt goes
        to the backend that does the work); it has no token limit and no
        Realtime transcription setting."""
        from app.services.ai.domains.voice.realtime_calls import _model_settings

        assert _model_settings(
            "openai:gpt-live-1", "cedar", 1200, instructions="Keep it short."
        ) == {"openai_voice": "cedar", "openai_live_instructions": "Keep it short."}

    def test_gemini_does_not_take_the_tv_for_you(self) -> None:
        """A TV in the room held Gemini's turn open: it heard "speech",
        never decided you had finished, and never answered - you could not
        be heard until you hung up and called back (2026-09-30). Stricter
        about what starts a turn, quicker to end one."""
        from app.services.ai.domains.voice.realtime_calls import _model_settings

        vad = _model_settings("google:gemini-3.8-live", None, None)["google_vad"]
        assert vad == {"start_sensitivity": "low", "end_sensitivity": "high"}


class TestDrivingACall:
    """``drive`` runs a call to its end, whichever way its audio travels."""

    @pytest.mark.asyncio
    async def test_it_saves_each_turn_tells_the_page_and_prices_the_call(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio

        from app.services.ai.domains.voice.realtime_calls import drive
        from tests._realtime import FakeRealtime

        await _priced(async_db_session, monkeypatch)
        conversation = await _conversation()
        realtime = FakeRealtime(_turn())
        seen: list[object] = []
        saved: list[bool] = []
        beside: list[object] = []

        async def alongside(session: object) -> None:
            beside.append(session)
            await asyncio.sleep(0)
            await session.close()  # type: ignore[attr-defined]

        async def on_event(event: object) -> None:
            seen.append(event)

        async def on_saved(cost: float) -> None:
            saved.append(cost)

        await drive(
            ai_service,
            realtime,
            conversation_id=conversation.id,
            model="google:gemini-3.8-live",
            agent_slug="voice",
            user_id=USER,
            alongside=alongside,
            on_event=on_event,
            on_saved=on_saved,
        )

        assert realtime.provider_session is None  # the relay's own session
        assert beside == [realtime.live]
        assert len(seen) == len(_turn()) and len(saved) == 1
        assert saved[0] > 0  # the call's running cost, for the call bar
        stored = await ai_service.get_conversation(conversation.id)
        reply = stored.messages[-1]
        assert reply.content == "You're $199.39 over."
        assert (reply.metadata["provider"], reply.metadata["model"]) == (
            "google",
            "gemini-3.8-live",
        )
        # the turn's own share of the call, for its footer, like a typed turn
        assert (reply.metadata["input_tokens"], reply.metadata["output_tokens"]) == (
            100,
            40,
        )
        assert reply.metadata["cost"] == pytest.approx(saved[0])
        (row,) = (await async_db_session.exec(select(LLMUsage))).all()
        assert (row.action, row.model_id) == ("realtime", "gemini-3.8-live")
        assert row.total_cost > 0  # priced at the catalog's Gemini rates

    @pytest.mark.asyncio
    async def test_a_card_shows_as_she_draws_it(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A chart is up while she talks about it, not once the turn is
        saved: each card drawn is told the moment its step finishes."""
        import asyncio

        from app.services.ai.domains.chat import cards
        from app.services.ai.domains.voice.realtime_calls import drive
        from tests._realtime import FakeRealtime

        await _priced(async_db_session, monkeypatch)
        conversation = await _conversation()
        order: list[object] = []

        async def on_event(event: object) -> None:
            if isinstance(event, FunctionToolCallEvent):  # her script draws
                staged = cards._staged.get()
                assert staged is not None
                staged.append({"kind": cards.MARKER, "id": "c1"})

        async def on_drawn(ids: list[str]) -> None:
            order.append(ids)

        async def on_saved(cost: float) -> None:
            order.append("saved")

        async def alongside(session: object) -> None:
            await asyncio.sleep(0)
            await session.close()  # type: ignore[attr-defined]

        await drive(
            ai_service,
            FakeRealtime(_turn()),
            conversation_id=conversation.id,
            model="google:gemini-3.8-live",
            agent_slug="voice",
            user_id=USER,
            alongside=alongside,
            on_event=on_event,
            on_drawn=on_drawn,
            on_saved=on_saved,
        )

        assert order == [["c1"], "saved"]
        stored = await ai_service.get_conversation(conversation.id)
        trace = stored.messages[-1].metadata["tool_trace"]
        assert trace[-1]["component"] == [{"kind": cards.MARKER, "id": "c1"}]
