"""What a case asserts about a turn: the tools it called, with what, in
what order, and what its answer leaves out.

Scored on the turn's ``tool_trace`` (``app/services/ai/service/trace.py``),
the steps the saved message keeps and Overseer shows, so a case checks
what a person reads. Pydantic Evals' own ``Contains`` and ``LLMJudge``
cover what the answer says.
"""

from dataclasses import dataclass, field
import json
from typing import Any

from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext

# Where the runner puts the turn's trace on each case (``set_eval_attribute``).
TRACE = "tool_trace"


@dataclass(frozen=True)
class ToolCall:
    """One call a turn made, its arguments parsed."""

    name: str
    args: dict[str, Any]


def _args(text: str) -> dict[str, Any]:
    """A trace entry's arguments: JSON text, clipped, so possibly unreadable."""
    try:
        parsed = json.loads(text) if text else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def calls_of(trace: list[dict[str, Any]]) -> list[ToolCall]:
    """Every call in a trace, in order: a script's dispatches follow it."""
    calls: list[ToolCall] = []
    for entry in trace:
        args = {"code": entry["code"]} if "code" in entry else _args(entry.get("args", ""))
        calls.append(ToolCall(entry["tool"], args))
        calls.extend(
            ToolCall(n["tool"], _args(n.get("args", ""))) for n in entry.get("nested", ())
        )
    return calls


def _calls(ctx: EvaluatorContext[Any, Any, Any]) -> list[ToolCall]:
    return calls_of(ctx.attributes.get(TRACE) or [])


@dataclass(repr=False)
class ToolCalls(Evaluator[Any, Any, Any]):
    """``tool`` was called, holding every one of ``args``: ``times`` times,
    or at least once when unset; ``times: 0`` says it never was."""

    tool: str
    times: int | None = None
    args: dict[str, Any] = field(default_factory=dict)

    def evaluate(self, ctx: EvaluatorContext[Any, Any, Any]) -> EvaluationReason:
        tried = [c.args for c in _calls(ctx) if c.name == self.tool]
        n = sum(self.args.items() <= held.items() for held in tried)
        passed = n > 0 if self.times is None else n == self.times
        wanted = "at least once" if self.times is None else f"{self.times}"
        return EvaluationReason(
            passed, f"{self.tool}: {n} matching of {tried or 'no calls'}, wanted {wanted}"
        )


@dataclass(repr=False)
class ToolOrder(Evaluator[Any, Any, Any]):
    """``tools`` were called in this order, others allowed between."""

    tools: list[str]

    def evaluate(self, ctx: EvaluatorContext[Any, Any, Any]) -> EvaluationReason:
        made = [call.name for call in _calls(ctx)]
        rest = iter(made)
        passed = all(tool in rest for tool in self.tools)
        return EvaluationReason(passed, f"called {made}")


@dataclass(repr=False)
class AnswerAvoids(Evaluator[Any, Any, Any]):
    """The answer says none of ``terms`` (any case)."""

    terms: list[str]

    def evaluate(self, ctx: EvaluatorContext[Any, Any, Any]) -> EvaluationReason:
        answer = str(ctx.output).lower()
        said = [term for term in self.terms if term.lower() in answer]
        return EvaluationReason(not said, f"said {said}" if said else "said none")


EVALUATORS = (ToolCalls, ToolOrder, AnswerAvoids)
