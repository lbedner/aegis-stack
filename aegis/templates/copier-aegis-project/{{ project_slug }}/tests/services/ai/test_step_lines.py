"""A chat's trail line per step, live and stored alike: the call itself, or
what the step is doing (``steps.doing``) where ``AI_CHAT_SHOW_CALLS`` is
off, so a viewer sees the agent's steps, not its code."""

import json

import pytest

from app.components.backend.api.ai.sse import _tool
from app.core.chat_transcript import trace_label
from app.core.config import settings
from app.services.ai.service.trace import tool_notice

SCRIPT = "# The AI service's wiring\nfound = await ontology()"


def _live_label(args: str) -> str:
    notice = tool_notice(
        "run_code",
        args=args,
        message_id="m",
        conversation_id=None,
        stream_delta=True,
    )
    return json.loads(_tool(notice).split("data: ", 1)[1])["label"]


def test_a_step_shows_its_call_by_default() -> None:
    assert trace_label({"tool": "run_code", "code": SCRIPT}) == (
        "run_code: found = await ontology()"
    )
    assert _live_label(json.dumps({"code": SCRIPT})) == (
        "run_code: found = await ontology()"
    )


def test_with_calls_hidden_a_step_reads_as_what_it_is_doing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AI_CHAT_SHOW_CALLS", False)

    assert trace_label({"tool": "run_code", "code": SCRIPT}) == (
        "The AI service's wiring"
    )
    assert trace_label({"tool": "bill_candidates", "args": "{}"}) == "Bill candidates"
    # Live, from the whole script: its preview has lost the comment.
    assert _live_label(json.dumps({"code": SCRIPT})) == "The AI service's wiring"

