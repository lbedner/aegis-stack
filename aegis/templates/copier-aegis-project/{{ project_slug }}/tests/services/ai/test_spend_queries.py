"""The money reads behind the Overseer's Costs section: what the AI service
spent per day and per action, how many users it spent on, the span of the
ledger, and what voice calls cost beside the model calls."""

from datetime import date, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.services.ai.domains.spend import queries, windows
from app.services.ai.domains.spend.schemas import ActionSpend
from app.services.ai.models.llm import LargeLanguageModel, LLMOrg, LLMUsage
from tests._session import opens

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


async def test_voice_spend_is_read_from_the_one_ledger(
    async_db_session: AsyncSession,
) -> None:
    """Speech and live calls are priced into ``llm_usage`` like any model
    call: the voice split reads them there, and the day's spend counts
    them once, with everything else."""
    async_db_session.add_all(
        [
            LLMUsage(
                model_id=model,
                action=action,
                timestamp=datetime(2026, 9, 4),
                input_tokens=0,
                output_tokens=0,
                total_cost=cost,
            )
            for model, action, cost in (
                ("gpt-transcribe", "stt", 0.25),
                ("tts-1", "tts", 0.75),
                ("gemini-3.8-live", "realtime", 1.5),
                ("gpt-x", "chat:assistant", 2.0),
            )
        ]
    )
    await async_db_session.commit()

    assert await queries.voice_spend(async_db_session, START, END) == {
        "Transcription": 0.25,
        "Speech": 0.75,
        "Live calls": 1.5,
    }
    assert await queries.daily_spend(async_db_session, START, END) == {
        date(2026, 9, 4): 4.5
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


async def test_usage_over_several_windows_in_one_read(
    async_db_session: AsyncSession,
) -> None:
    """Each window's requests, tokens and cost per vendor (``unknown``: a
    model not in the catalog) and action; None is the whole ledger."""
    await _ledger(async_db_session)

    found = await queries.usage_windows(
        async_db_session, [datetime(2026, 9, 4), START, None]
    )

    assert found == {
        ("unknown", "stream_chat:assistant"): [(0, 0, 0.0), (1, 15, 1.0), (1, 15, 1.0)],
        ("unknown", "chat:assistant"): [(0, 0, 0.0), (1, 15, 0.5), (2, 30, 9.5)],
        ("unknown", "document_extraction"): [(1, 15, 2.0)] * 3,
    }


async def test_the_ai_services_spend_by_window(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What its node's ``now`` carries: today, the last 7 days and all
    time, each saying what it covers."""
    async_db_session.add(_call(utcnow(), "chat:assistant", 0.25))
    await async_db_session.commit()
    monkeypatch.setattr(windows, "get_async_session", opens(async_db_session))

    found = await windows.spend_windows()

    assert [(w.label, w.total_requests, w.total_cost) for w in found] == [
        ("today", 1, 0.25),
        ("last 7 days", 1, 0.25),
        ("all time", 1, 0.25),
    ]
    assert found[-1].since is None


async def test_a_window_reads_in_cents(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Money as a person says it: a ledger's fractions of a cent would be
    read aloud as more than they are."""
    async_db_session.add_all(
        [
            _call(utcnow(), "realtime", 2.282995),
            _call(utcnow(), "chat:assistant", 0.012076),
        ]
    )
    await async_db_session.commit()
    monkeypatch.setattr(windows, "get_async_session", opens(async_db_session))

    week = (await windows.spend_windows())[1]

    assert week.total_cost == 2.3
    assert week.by_mode == {"voice": 2.28, "text": 0.01}


async def test_each_window_says_what_it_cost_by_vendor_by_action_and_by_mode(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Who served it (the catalog's vendor; ``unknown`` for a model not in
    it), what it was for (a voice kind by its name) and whether it was
    voice or text, largest first."""
    org = LLMOrg(slug="openai", name="openai", color="#000", icon_path="")
    async_db_session.add(org)
    await async_db_session.commit()
    await async_db_session.refresh(org)
    async_db_session.add(
        LargeLanguageModel(model_id="gpt-x", title="GPT X", served_by_org_id=org.id)
    )
    call = _call(utcnow(), "realtime", 1.0)
    call.model_id = "voice-y"
    async_db_session.add_all([_call(utcnow(), "chat:assistant", 0.25), call])
    await async_db_session.commit()
    monkeypatch.setattr(windows, "get_async_session", opens(async_db_session))

    week = (await windows.spend_windows())[1]

    assert list(week.by_vendor.items()) == [("unknown", 1.0), ("openai", 0.25)]
    assert list(week.by_action.items()) == [
        ("Live calls", 1.0),
        ("chat:assistant", 0.25),
    ]
    assert list(week.by_mode.items()) == [("voice", 1.0), ("text", 0.25)]


async def test_the_spend_aggregate_is_one_of_the_apps_windows(
    async_db_session: AsyncSession,
) -> None:
    """``ai.spend``: the node's query, for the window asked, named as its
    range chip is; a call before the window is not in it."""
    from app.services.ai import aggregates

    async_db_session.add(_call(utcnow(), "chat:assistant", 0.25))
    async_db_session.add(_call(utcnow() - timedelta(days=30), "chat:assistant", 4.0))
    await async_db_session.commit()
    (counted,) = aggregates.AGGREGATES

    week = await counted.read(async_db_session, 7)

    assert (week.label, week.total_requests, week.total_cost) == ("7d", 1, 0.25)
    every = await counted.read(async_db_session, None)
    assert (every.label, every.total_requests) == ("All", 2)
