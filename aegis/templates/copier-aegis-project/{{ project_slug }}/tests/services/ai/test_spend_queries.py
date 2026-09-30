"""The money reads behind the Overseer's Costs section: what the AI service
spent per day and per action, how many users it spent on, the span of the
ledger, and what voice calls cost beside the model calls."""

from datetime import UTC, date, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.spend import queries
from app.services.ai.domains.spend.schemas import ActionSpend
from app.services.ai.models.llm import LLMUsage

START = datetime(2026, 9, 1)
END = datetime(2026, 10, 1)


def _call(
    when: datetime, action: str, cost: float, user: str | None = "u1"
) -> LLMUsage:
    return LLMUsage(
        model_id="gpt-x",
        user_id=user,
        timestamp=when,
        input_tokens=10,
        output_tokens=5,
        total_cost=cost,
        success=True,
        action=action,
    )


async def _ledger(db: AsyncSession) -> None:
    db.add_all(
        [
            _call(datetime(2026, 9, 3, 9), "stream_chat:assistant", 1.0),
            _call(datetime(2026, 9, 3, 18), "chat:assistant", 0.5, user="u2"),
            _call(datetime(2026, 9, 5, 12), "document_extraction", 2.0, user=None),
            _call(datetime(2026, 8, 30, 12), "chat:assistant", 9.0),  # before
        ]
    )
    await db.commit()


async def test_spend_per_day(async_db_session: AsyncSession) -> None:
    await _ledger(async_db_session)
    days = await queries.daily_spend(async_db_session, START, END)
    assert days == {date(2026, 9, 3): 1.5, date(2026, 9, 5): 2.0}


async def test_spend_per_action(async_db_session: AsyncSession) -> None:
    await _ledger(async_db_session)
    actions = await queries.spend_by_action(async_db_session, START, END)
    assert actions == {
        "stream_chat:assistant": ActionSpend(calls=1, cost=1.0),
        "chat:assistant": ActionSpend(calls=1, cost=0.5),
        "document_extraction": ActionSpend(calls=1, cost=2.0),
    }


async def test_the_users_it_spent_on(async_db_session: AsyncSession) -> None:
    await _ledger(async_db_session)
    assert await queries.spenders(async_db_session, START, END) == 2


async def test_the_first_call_on_record(async_db_session: AsyncSession) -> None:
    await _ledger(async_db_session)
    assert await queries.first_call(async_db_session) == datetime(2026, 8, 30, 12)


async def test_an_empty_ledger_has_no_first_call(
    async_db_session: AsyncSession,
) -> None:
    assert await queries.first_call(async_db_session) is None


async def test_voice_spend(async_db_session: AsyncSession) -> None:
    import pytest

    voice = pytest.importorskip("app.services.ai.models.voice_usage")
    if not hasattr(voice, "STTUsage"):
        pytest.skip("no voice in this stack")
    async_db_session.add_all(
        [
            voice.STTUsage(
                provider="openai_whisper",
                timestamp=datetime(2026, 9, 4, tzinfo=UTC),
                total_cost=0.25,
            ),
            voice.TTSUsage(
                provider="openai",
                timestamp=datetime(2026, 9, 4, tzinfo=UTC),
                total_cost=0.75,
            ),
        ]
    )
    await async_db_session.commit()
    assert await queries.voice_spend(async_db_session, START, END) == {
        "Transcription": 0.25,
        "Speech": 0.75,
    }


async def test_spend_per_user_and_action(async_db_session: AsyncSession) -> None:
    await _ledger(async_db_session)
    spend = await queries.spend_by_user_action(async_db_session, START, END)
    assert spend == {
        "u1": {"stream_chat:assistant": ActionSpend(calls=1, cost=1.0)},
        "u2": {"chat:assistant": ActionSpend(calls=1, cost=0.5)},
        None: {"document_extraction": ActionSpend(calls=1, cost=2.0)},
    }


async def test_a_window_ends_before_its_end(async_db_session: AsyncSession) -> None:
    """Every ledger read takes ``[start, end)``: a call at midnight on the
    1st is the new month's, counted once, in the daily spend and the model
    breakdown alike."""
    from app.services.ai.domains.llm.queries import usage_by_model

    async_db_session.add(_call(END, "chat:assistant", 5.0))
    await async_db_session.commit()
    assert await queries.daily_spend(async_db_session, START, END) == {}
    models = await usage_by_model(
        async_db_session, user_id=None, start_time=START, end_time=END
    )
    assert models == []
