"""The trace evaluators: what a case asserts about the tools a turn called."""

from typing import Any

from pydantic_evals.evaluators import EvaluatorContext

from app.services.ai.domains.evals.evaluators import (
    AnswerAvoids,
    ToolCalls,
    ToolOrder,
    calls_of,
)

# The trace ``record_tool_call`` / ``record_tool_result`` build: a direct
# call, then a script whose sandbox dispatched two more.
TRACE: list[dict[str, Any]] = [
    {"tool": "paper", "args": '{"document_id": 6}', "result": "a letter"},
    {
        "tool": "run_code",
        "code": "led = await ledger(months=3)",
        "result": "42",
        "nested": [
            {"tool": "ledger", "args": '{"months": 3}'},
            {"tool": "accounts", "args": ""},
        ],
    },
]


def _ctx(output: str = "", trace: list[dict[str, Any]] = TRACE) -> EvaluatorContext:
    return EvaluatorContext(
        name="case",
        inputs=None,
        metadata=None,
        expected_output=None,
        output=output,
        duration=1.0,
        _span_tree=None,
        attributes={"tool_trace": trace},
        metrics={},
    )


def test_a_scripts_dispatches_count_as_calls_after_the_script() -> None:
    assert [c.name for c in calls_of(TRACE)] == [
        "paper",
        "run_code",
        "ledger",
        "accounts",
    ]
    assert calls_of(TRACE)[0].args == {"document_id": 6}


def test_tool_calls_counts_at_least_once_exactly_or_never() -> None:
    assert ToolCalls("ledger").evaluate(_ctx()).value is True
    assert ToolCalls("paper", times=1).evaluate(_ctx()).value is True
    assert ToolCalls("paper", times=2).evaluate(_ctx()).value is False
    never = ToolCalls("delete_everything", times=0).evaluate(_ctx())
    assert never.value is True
    assert ToolCalls("paper", times=0).evaluate(_ctx()).reason


def test_tool_calls_with_args_counts_the_calls_holding_them() -> None:
    assert ToolCalls("paper", args={"document_id": 6}).evaluate(_ctx()).value is True
    assert ToolCalls("ledger", args={"months": 3}).evaluate(_ctx()).value is True
    assert ToolCalls("paper", args={"document_id": 7}).evaluate(_ctx()).value is False
    assert ToolCalls("paper", 0, {"document_id": 7}).evaluate(_ctx()).value is True


def test_tool_order_is_a_subsequence() -> None:
    assert ToolOrder(["paper", "ledger"]).evaluate(_ctx()).value is True
    assert ToolOrder(["ledger", "paper"]).evaluate(_ctx()).value is False


def test_answer_avoids_names_what_it_found() -> None:
    clean = AnswerAvoids(["refund"]).evaluate(_ctx("Your balance is 42."))
    assert clean.value is True
    said = AnswerAvoids(["Refund"]).evaluate(_ctx("A refund is on its way."))
    assert said.value is False
    assert "refund" in (said.reason or "").lower()


def test_a_turn_with_no_tools_called_none() -> None:
    assert ToolCalls("paper", times=0).evaluate(_ctx(trace=[])).value is True


def test_a_scripts_long_arguments_reach_the_trace_whole() -> None:
    """A call a script dispatched keeps its arguments as a direct call
    does, not the trail's one-line preview, so ``args`` can match them."""
    from pydantic_ai.messages import FunctionToolResultEvent, ToolCallPart, ToolReturnPart

    from app.services.ai.service.trace import record_tool_result

    query = "q" * 300
    part = ToolReturnPart(
        tool_name="run_code",
        content="done",
        tool_call_id="p",
        metadata={"tool_calls": {"p__1": ToolCallPart("search", {"query": query}, "p__1")}},
    )
    trace: list[dict[str, Any]] = []
    record_tool_result(trace, FunctionToolResultEvent(part=part))

    held = ToolCalls("search", args={"query": query}).evaluate(_ctx(trace=trace))
    assert held.value is True
