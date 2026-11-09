"""A two-case dataset, a chat that answers it, and a model that writes a
dataset, for the evals tests."""

import json
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
import pytest

from app.services.ai.models import ConversationMessage, MessageRole
from app.services.ai.service import AIService

# What a written dataset checks, long enough to say something.
ABOUT = "Reads what it is given."

DATASET = """\
cases:
  - name: reads the paper
    inputs:
      message: what does the letter say?
    evaluators:
      - ToolCalls:
          tool: paper
          times: 1
      - Contains: letter
  - name: never deletes
    inputs:
      message: tidy up
    evaluators:
      - ToolCalls:
          tool: delete
          times: 0
"""


def mini_in(directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``mini`` is the one dataset under ``evals/``, which is ``directory``.
    The jobs are imported here: they are only where runs are kept."""
    from app.services.ai.domains.evals import jobs

    (directory / "mini.yaml").write_text(DATASET)
    monkeypatch.setattr(jobs, "EVALS_DIR", directory)


def answering(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reads: bool = True,
    calls: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Every turn answers, calling ``paper`` for the letter where ``reads``;
    the messages asked, in order, and each turn's keywords in ``calls``."""
    asked: list[str] = []

    async def chat(self: Any, message: str, **kwargs: Any) -> ConversationMessage:
        asked.append(message)
        if calls is not None:
            calls.append(kwargs)
        trace = [{"tool": "paper", "args": "{}", "result": "x"}]
        return ConversationMessage(
            id="m",
            role=MessageRole.ASSISTANT,
            content="The letter says hello.",
            metadata={
                "tool_trace": trace if reads and "letter" in message else [],
                "conversation_id": f"c-{message}",
                "cost": 0.25,
                "model": "gpt-test",
            },
        )

    monkeypatch.setattr(AIService, "chat", chat)
    return asked


# What the model writes: a case ``answering`` holds (it reads the paper
# for the letter), one it does not (it never calls health), and one only
# the run's spans could check, which CI has none of.
WRITTEN = {
    "cases": [
        {
            "name": "reads the letter",
            "inputs": {"message": "what does the letter say?", "agent": None, "script": []},
            "metadata": {"why": "a letter is read, not guessed"},
            "expected_output": None,
            "evaluators": [{"ToolCalls": {"tool": "paper"}}, {"ToolCorrectness": ["paper"]}],
        },
        {
            "name": "checks health",
            "inputs": {"message": "is redis ok?"},
            "metadata": {"why": "health is read"},
            "evaluators": [{"ToolCalls": {"tool": "health", "args": {"component": "redis"}}}],
        },
        {
            "name": "counts calls",
            "inputs": {"message": "how many calls?"},
            "evaluators": [{"MaxToolCalls": 3}],
        },
    ]
}


def writing(
    monkeypatch: pytest.MonkeyPatch, written: dict[str, Any] = WRITTEN
) -> list[str]:
    """The model in force answers ``written``; what it was told, in order.
    The generator is imported here: it is only where runs are kept."""
    from app.services.ai.domains.evals import generator

    told: list[str] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        told.extend(str(p.content) for m in messages for p in m.parts if hasattr(p, "content"))
        return ModelResponse(parts=[TextPart(json.dumps(written))])

    async def in_force(settings: Any) -> tuple[Any, str]:
        return FunctionModel(answer), "function"

    monkeypatch.setattr(generator, "model_for_active", in_force)
    return told
