"""Running a dataset: each case a real turn, scored on its reply."""

from pathlib import Path
from typing import Any

import pytest

from app.services.ai.domains.evals import runner
from app.services.ai.domains.evals.datasets import load
from app.services.ai.models import ConversationMessage, MessageRole

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


async def test_each_case_is_a_turn_scored_on_its_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    asked: list[str] = []

    async def chat(self: Any, message: str, **kwargs: Any) -> ConversationMessage:
        asked.append(message)
        trace = [{"tool": "paper", "args": "{}", "result": "x"}]
        return ConversationMessage(
            id="m1",
            role=MessageRole.ASSISTANT,
            content="The letter says hello.",
            metadata={"tool_trace": trace if "letter" in message else []},
        )

    monkeypatch.setattr(runner.AIService, "chat", chat)
    report = await runner.run_dataset("mini", directory=tmp_path)

    assert sorted(asked) == ["tidy up", "what does the letter say?"]
    results = {
        case.name: {name: r.value for name, r in case.assertions.items()}
        for case in report.cases
    }
    assert results["reads the paper"] == {"ToolCalls": True, "Contains": True}
    assert results["never deletes"] == {"ToolCalls": True}


async def test_scripted_mode_refuses_a_case_without_a_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    report = await runner.run_dataset("mini", directory=tmp_path, scripted=True)
    assert not report.cases
    assert len(report.failures) == 2


async def test_a_run_reports_to_logfire_as_its_own_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where the stack has observability, a run configures Logfire as the
    ``evals`` process; the token stays the only switch."""
    tracing = pytest.importorskip("app.components.backend.middleware.logfire_tracing")
    units: list[str] = []
    monkeypatch.setattr(tracing, "configure_logfire", lambda unit: units.append(unit))
    (tmp_path / "mini.yaml").write_text("cases: []\n")

    await runner.run_dataset("mini", directory=tmp_path)

    assert units == ["evals"]


def test_the_starter_dataset_loads_and_every_case_is_scripted() -> None:
    dataset = load("starter")
    assert dataset.cases
    assert all(case.inputs.script for case in dataset.cases)


@pytest.mark.queryspy(allow_n_plus_one=True)  # one real turn per case
async def test_the_starter_plays_through_the_real_turn() -> None:
    """Each scripted case through ``AIService.chat``: its tools run, its
    trace is kept, and every assertion holds."""
    report = await runner.run_dataset("starter", scripted=True)

    assert not report.failures, [f.error_message for f in report.failures]
    assert report.cases
    for case in report.cases:
        assert all(r.value for r in case.assertions.values()), case.name
