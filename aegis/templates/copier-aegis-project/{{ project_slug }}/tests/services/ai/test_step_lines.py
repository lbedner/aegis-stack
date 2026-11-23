"""A chat's trail line per step, live and stored alike: the call itself, or
what the step is doing (``steps.doing``) where ``AI_CHAT_SHOW_CALLS`` is
off, so a viewer sees the agent's steps, not its code."""

import json

import pytest

from app.components.backend.api.ai.sse import _tool
from app.core.chat_transcript import trace_label, trail_rows
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
    # A script by what it is for: the reads under it say what it called.
    assert trace_label({"tool": "run_code", "code": SCRIPT}) == (
        "run_code: The AI service's wiring"
    )
    assert _live_label(json.dumps({"code": SCRIPT})) == (
        "run_code: The AI service's wiring"
    )
    # One without its comment, by its first line of code.
    assert trace_label({"tool": "run_code", "code": "x = await ontology()"}) == (
        "run_code: x = await ontology()"
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


def test_a_scripts_reads_sit_under_it_live_and_stored() -> None:
    """A read a script dispatched is not a call of the model's: it shows
    under its script, marked, live and stored alike, and is no step."""
    read = {"tool": "errors", "args": '{"window_seconds": 604800}'}
    live = tool_notice(
        "errors",
        args=read["args"],
        message_id="m",
        conversation_id=None,
        stream_delta=True,
        inside=True,
    )
    rows = trail_rows([{"tool": "run_code", "code": SCRIPT, "nested": [read]}], "/m")

    assert [(row["label"], row.get("inside", False)) for row in rows] == [
        ("run_code: The AI service's wiring", False),
        ("└ errors(window_seconds=604800)", True),
    ]
    assert json.loads(_tool(live).split("data: ", 1)[1])["label"] == rows[1]["label"]
    assert rows[1]["url"] == rows[0]["url"] == "/m/runs/0"

