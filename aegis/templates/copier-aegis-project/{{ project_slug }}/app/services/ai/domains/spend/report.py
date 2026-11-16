"""What models and voice cost, by kind and model, and each live call
costed with the answers it handed off: read back from the one ledger
(``llm_usage``), for the Costs section and ``ai costs``."""

from datetime import datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.ai.domains.spend import queries
from app.services.ai.domains.spend.recording import REALTIME_ACTION, VOICE_ACTIONS
from app.services.ai.domains.spend.schemas import CallSpend, KindModelSpend

# What every action that is not a voice one is: a model call (a chat or
# agent turn, a job's).
MODEL_CALLS = "Model calls"
CALLS_SHOWN = 50
# How a call ended, as the Costs section and ``ai costs`` say it.
ENDED = {True: "Ended", False: "Failed"}


def kind(action: str) -> str:
    """The kind of use an action is: a voice kind by its name, else a
    model call."""
    return VOICE_ACTIONS.get(action, MODEL_CALLS)


async def models_by_kind(
    session: AsyncSession, start: datetime, end: datetime
) -> list[KindModelSpend]:
    """Each model under each kind it was used for in ``[start, end)``,
    most spent first."""
    spent: dict[tuple[str, str], list[float]] = {}
    rows = await queries.spend_by_action_model(session, start, end)
    for action, model, *figures in rows:
        total = spent.setdefault((kind(action), model), [0.0] * len(figures))
        for i, value in enumerate(figures):
            total[i] += value
    models = [
        KindModelSpend(
            kind=k,
            model_id=model,
            uses=int(uses),
            seconds=seconds,
            tokens=int(tokens),
            cost=cost,
        )
        for (k, model), (uses, seconds, tokens, cost) in spent.items()
    ]
    return sorted(models, key=lambda row: -row.cost)


async def live_calls(
    session: AsyncSession, start: datetime, end: datetime
) -> list[CallSpend]:
    """The window's live calls, newest first: each with what the turns it
    handed off cost (a picture looked at), the replies the call bar counted
    as they landed."""
    calls = await queries.rows_of(session, REALTIME_ACTION, start, end, CALLS_SHOWN)
    answers = await queries.handed_off_spend(
        session, [c.id for c in calls if c.id is not None]
    )
    return [
        CallSpend(
            started=call.timestamp,
            model_id=call.model_id,
            seconds=call.audio_seconds or 0.0,
            call_cost=call.total_cost,
            answers_cost=answers.get(call.id or 0, 0.0),
            success=call.success,
        )
        for call in calls
    ]
