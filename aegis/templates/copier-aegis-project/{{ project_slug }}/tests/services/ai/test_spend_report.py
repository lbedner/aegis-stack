"""What models and voice cost, read back from the one ledger.

``llm_usage`` holds model calls (chat and agent turns), live calls,
transcriptions and spoken replies. The report lists it by kind and model,
and costs each live call as itself plus the answers given during it.
"""

from datetime import datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.conversation import Conversation, ConversationMessage
from app.services.ai.domains.spend import report
from app.services.ai.models.llm import LLMUsage

START = datetime(2026, 9, 1)
END = datetime(2026, 10, 1)
CALLED = datetime(2026, 9, 27, 17)


def _row(**fields: object) -> LLMUsage:
    base: dict[str, object] = {
        "model_id": "gpt-x",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_cost": 0.0,
        "timestamp": CALLED + timedelta(days=1),
        "action": "stream_chat:assistant",
    }
    return LLMUsage(**{**base, **fields})


def _reply(cost: float, call: int | None = None) -> ConversationMessage:
    """A reply in the call's conversation: a turn the call handed off names
    it (``call``), as the turn's stream writes it."""
    meta: dict[str, object] = {"cost": cost} | ({"call": call} if call else {})
    return ConversationMessage(conversation_id="c-1", role="assistant", meta_data=meta)


@pytest.fixture
async def ledger(async_db_session: AsyncSession) -> AsyncSession:
    # A ten-minute call priced by the minute.
    call = _row(
        action="realtime",
        model_id="gpt-live-1",
        conversation_id="c-1",
        audio_seconds=600,
        total_cost=0.50,
        timestamp=CALLED,
    )
    async_db_session.add_all(
        [
            # A typed turn.
            _row(input_tokens=1_000, output_tokens=200, total_cost=0.02),
            call,
            # Two answers it handed off, and a turn typed in another tab
            # into the same conversation while it ran.
            _row(
                conversation_id="c-1",
                total_cost=0.01,
                timestamp=CALLED + timedelta(minutes=5),
            ),
            _row(
                action="chat:voice",
                conversation_id="c-1",
                total_cost=0.03,
                timestamp=CALLED + timedelta(minutes=2),
            ),
            _row(
                action="chat:voice",
                conversation_id="c-1",
                total_cost=0.04,
                timestamp=CALLED + timedelta(minutes=8),
            ),
            # The same conversation typed into a day later is not the call.
            _row(conversation_id="c-1", total_cost=0.05),
            # A call priced by its tokens, that failed.
            _row(
                action="realtime",
                model_id="gpt-realtime-2.1",
                conversation_id="c-2",
                audio_seconds=120,
                input_tokens=30_000,
                total_cost=0.17,
                success=False,
                timestamp=CALLED - timedelta(days=1),
            ),
            _row(action="stt", model_id="gpt-transcribe", audio_seconds=60),
            _row(action="tts", model_id="gpt-4o-mini-tts", total_cost=0.01),
            # Outside the window.
            _row(total_cost=9.0, timestamp=START - timedelta(days=1)),
            Conversation(id="c-1", user_id="7"),
        ]
    )
    await async_db_session.commit()
    async_db_session.add_all(
        [_reply(0.03, call.id), _reply(0.04, call.id), _reply(0.01), _reply(0.05)]
    )
    await async_db_session.commit()
    return async_db_session


async def test_each_model_under_the_kind_it_was_used_for(
    ledger: AsyncSession,
) -> None:
    models = await report.models_by_kind(ledger, START, END)
    keyed = {(m.kind, m.model_id): m for m in models}
    assert set(keyed) == {
        ("Model calls", "gpt-x"),
        ("Live calls", "gpt-live-1"),
        ("Live calls", "gpt-realtime-2.1"),
        ("Transcription", "gpt-transcribe"),
        ("Speech", "gpt-4o-mini-tts"),
    }
    chat = keyed[("Model calls", "gpt-x")]
    assert (chat.uses, chat.tokens) == (5, 1_200)
    assert chat.cost == pytest.approx(0.02 + 0.03 + 0.04 + 0.05 + 0.01)
    assert keyed[("Live calls", "gpt-live-1")].seconds == pytest.approx(600)
    # Most spent first.
    assert [m.model_id for m in models][:2] == ["gpt-live-1", "gpt-realtime-2.1"]


async def test_a_call_costs_itself_plus_its_answers(ledger: AsyncSession) -> None:
    calls = await report.live_calls(ledger, START, END)
    assert [c.model_id for c in calls] == ["gpt-live-1", "gpt-realtime-2.1"]
    call, failed = calls
    assert call.seconds == pytest.approx(600)
    assert call.call_cost == pytest.approx(0.50)
    # The two answers it handed off: not a turn typed beside it, nor a day
    # later. What the call bar counted as each landed.
    assert call.answers_cost == pytest.approx(0.07)
    assert call.total == pytest.approx(0.57)
    assert call.success and not failed.success
    assert failed.answers_cost == 0.0


async def test_no_calls_is_no_rows(async_db_session: AsyncSession) -> None:
    assert await report.live_calls(async_db_session, START, END) == []
