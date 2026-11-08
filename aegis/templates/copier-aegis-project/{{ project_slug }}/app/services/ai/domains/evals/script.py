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


class Step(BaseModel):
    """One response: a call to ``tool`` with ``args``, or ``text``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str | None = None
    args: dict[str, Any] = {}
    text: str = ""


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
