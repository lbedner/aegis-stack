"""A two-case dataset, and a chat that answers it, for the runner's tests."""

from typing import Any

import pytest

from app.services.ai.models import ConversationMessage, MessageRole
from app.services.ai.service import AIService

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


def answering(monkeypatch: pytest.MonkeyPatch, *, reads: bool = True) -> list[str]:
    """Every turn answers, calling ``paper`` for the letter where ``reads``;
    the messages asked, in order."""
    asked: list[str] = []

    async def chat(self: Any, message: str, **kwargs: Any) -> ConversationMessage:
        asked.append(message)
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
