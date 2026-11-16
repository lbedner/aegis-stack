"""Why a turn's answer has not started yet, when its engine can say.

The chat stream names a quiet stretch (``core.concurrency.announce_waiting``)
and asks this once per stretch. A local model may be loading, tens of
seconds of silence before its first token: "loading - 40s" is the same wait
as "waiting 40s" with the part that says it will finish. The turn's model
is the one its prompt was built for (``self_context``); its engine, through
the inference interface, says whether that model is in memory. A cloud
model, or a stack without the inference component, has no reason to give.
"""

from contextvars import ContextVar

from app.core.discovery import present
from app.services.ai.domains.chat.self_context import TurnContext, current_turn
from app.services.ai.models.provider_names import LOCAL_PROVIDERS

INFERENCE = present("app.components.inference")
THINKING = "thinking"
# The turn whose model was found in memory: it stays so for the turn, so
# its engine is not asked again (each quiet stretch asked it, through every
# tool run and model round). A stream's stretches share one context.
_thinking: ContextVar[TurnContext | None] = ContextVar("thinking", default=None)


async def waiting_reason() -> str | None:
    """A short phrase for why nothing has arrived this turn, or None."""
    turn = current_turn()
    if not (INFERENCE and turn and turn.model and turn.provider in LOCAL_PROVIDERS):
        return None
    if _thinking.get() is turn:
        return THINKING
    from app.components.inference import get_inference_engine

    reason = await get_inference_engine(turn.provider).waiting_reason(turn.model)
    if reason == THINKING:
        _thinking.set(turn)
    return reason
