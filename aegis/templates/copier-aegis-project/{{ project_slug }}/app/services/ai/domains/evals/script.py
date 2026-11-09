"""A case's script: the turn it would take, played without a model.

Each step is one model response, a tool call or the answer, in order, so
CI runs a case through the real turn (its tools, its trace, its saved
message) for free and the same way every time.
"""

from collections.abc import AsyncIterator
import json
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

from app.core.tools import RUN_CODE
from app.services.ai.service.trace import TRACE_CODE_CAP


class Step(BaseModel):
    """One response: a call to ``tool`` with ``args``, or ``text``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str | None = None
    args: dict[str, Any] = {}
    text: str = ""


def args_of(entry: dict[str, Any], *, whole: bool = False) -> dict[str, Any]:
    """A trace entry's arguments: the code it ran, else its JSON text. The
    trace clips both (``TRACE_CODE_CAP``), so they may be cut short: read
    as far as they go (unreadable JSON is none), or, where they must be
    ``whole``, ValueError."""
    if "code" in entry:
        if whole and len(entry["code"]) >= TRACE_CODE_CAP:
            raise ValueError("code too long for the trace to keep whole")
        return {"code": entry["code"]}
    try:
        parsed = json.loads(entry.get("args") or "{}")
    except ValueError:
        if whole:
            raise
        return {}
    return parsed if isinstance(parsed, dict) else {}


def recorded(trace: list[dict[str, Any]], answer: str) -> list[Step]:
    """The script a real turn took, from its trace: each call the model made
    (a script's dispatches replay as it runs), then ``answer``. ValueError
    for a call whose arguments the trace clipped."""
    calls = [Step(tool=entry["tool"], args=args_of(entry, whole=True)) for entry in trace]
    return [*calls, Step(text=answer)]


def in_code_mode(steps: list[Step]) -> bool:
    """Whether the turn a script recorded wrote code (``run_code``): its
    calls are made that way, so it plays in code mode."""
    return any(step.tool == RUN_CODE for step in steps)


def scripted_model(steps: list[Step]) -> FunctionModel:
    """A model that answers each request with the next step, streamed as a
    turn streams; past the last it answers the last step's text."""

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        taken = sum(isinstance(m, ModelResponse) for m in messages)
        now = steps[taken] if taken < len(steps) else Step(text=steps[-1].text)
        if now.tool:
            yield {0: DeltaToolCall(name=now.tool, json_args=json.dumps(now.args))}
        else:
            yield now.text

    return FunctionModel(stream_function=stream, model_name="scripted")
