"""Running a dataset: each case a real turn, scored on its reply."""

from pathlib import Path
from typing import Any

import pytest

from app.services.ai.domains.chat.agent_loader import CODE_MODE_OVERRIDE
from app.services.ai.domains.evals import runner
from app.services.ai.domains.evals.datasets import load, names
from app.services.ai.service.turn import HEARS_NOW
from tests.services.ai.evals._mini import DATASET, answering


async def test_each_case_is_a_turn_scored_on_its_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    asked = answering(monkeypatch)
    report = await runner.run_dataset("mini", directory=tmp_path)

    assert sorted(asked) == ["tidy up", "what does the letter say?"]
    results = {
        case.name: {name: r.value for name, r in case.assertions.items()}
        for case in report.cases
    }
    assert results["reads the paper"] == {"ToolCalls": True, "Contains": True}
    assert results["never deletes"] == {"ToolCalls": True}


async def test_each_turn_is_an_admins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The system's reads (its health, errors, parts) are an admin's, and
    only an admin starts a run."""
    (tmp_path / "mini.yaml").write_text(DATASET)
    calls: list[dict[str, Any]] = []
    answering(monkeypatch, calls=calls)
    await runner.run_dataset("mini", directory=tmp_path)

    assert [call["admin"] for call in calls] == [True, True]


async def test_no_turn_hears_what_is_wrong_right_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A case is scored on its message alone: with a check failing, or no
    webserver to ask, a greeting would otherwise be answered with a read."""
    (tmp_path / "mini.yaml").write_text(DATASET)
    heard: list[bool] = []

    async def chat(self: Any, message: str, **kwargs: Any) -> Any:
        heard.append(HEARS_NOW.get())
        raise RuntimeError("stop")

    monkeypatch.setattr(runner.AIService, "chat", chat)

    await runner.run_dataset("mini", directory=tmp_path)

    assert heard == [False, False]
    assert HEARS_NOW.get() is True


async def test_scripted_mode_refuses_a_case_without_a_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    report = await runner.run_dataset("mini", directory=tmp_path, scripted=True)
    assert not report.cases
    assert len(report.failures) == 2


async def test_a_scripted_run_leaves_out_the_checks_that_read_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No span is kept where a script plays, so a check that reads them
    waits for a real run; a case left with no check fails, never passes
    unchecked."""
    (tmp_path / "spans.yaml").write_text(
        "cases:\n"
        "  - name: checked both ways\n"
        "    inputs:\n"
        "      message: what does the letter say?\n"
        "      script: [{tool: paper}, {text: The letter says hello.}]\n"
        "    evaluators:\n"
        "      - Contains: letter\n"
        "      - MaxToolCalls: 3\n"
        "  - name: only spans\n"
        "    inputs:\n"
        "      message: tidy up\n"
        "      script: [{text: done}]\n"
        "    evaluators:\n"
        "      - MaxToolCalls: 3\n"
    )
    answering(monkeypatch)

    report = await runner.run_dataset("spans", directory=tmp_path, scripted=True)

    (case,) = report.cases
    assert set(case.assertions) == {"Contains"} and not case.evaluator_failures
    (failure,) = report.failures
    assert failure.name == "only spans" and "no check" in failure.error_message


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


async def test_each_case_is_reported_as_it_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    answering(monkeypatch)
    labels: list[str] = []

    await runner.run_dataset("mini", directory=tmp_path, report=labels.append)

    assert labels == ["1 of 2 · reads the paper", "2 of 2 · never deletes"]


async def test_a_run_can_name_the_model_it_runs_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    answering(monkeypatch)
    seen: list[str] = []
    chat = runner.AIService.chat

    async def noting(self: runner.AIService, message: str, **kwargs: object) -> object:
        seen.append(self.config.model)
        return await chat(self, message, **kwargs)

    monkeypatch.setattr(runner.AIService, "chat", noting)

    await runner.run_dataset("mini", directory=tmp_path, model="gpt-other")

    assert seen == ["gpt-other", "gpt-other"]


async def test_a_script_plays_in_the_mode_it_was_recorded_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A script whose turn wrote code plays in code mode, one that called
    tools directly plays without, whatever the agent is set to now."""
    (tmp_path / "modes.yaml").write_text(
        "evaluators:\n"
        "  - Contains: ok\n"
        "cases:\n"
        "  - name: wrote code\n"
        "    inputs:\n"
        "      message: a\n"
        "      script: [{tool: run_code, args: {code: x}}, {text: ok}]\n"
        "  - name: called directly\n"
        "    inputs:\n"
        "      message: b\n"
        "      script: [{tool: health}, {text: ok}]\n"
    )
    modes: list[bool | None] = []

    async def chat(self: Any, message: str, **kwargs: Any) -> Any:
        modes.append(CODE_MODE_OVERRIDE.get())
        raise RuntimeError("stop")

    monkeypatch.setattr(runner.AIService, "chat", chat)

    await runner.run_dataset("modes", directory=tmp_path, scripted=True)

    assert modes == [True, False]
    assert CODE_MODE_OVERRIDE.get() is None


def test_every_shipped_dataset_loads_and_every_case_is_scripted() -> None:
    for name in names():
        dataset = load(name)
        assert dataset.cases, name
        assert all(case.inputs.script for case in dataset.cases), name


@pytest.mark.queryspy(allow_n_plus_one=True)  # one real turn per case
@pytest.mark.parametrize("name", names())
async def test_every_shipped_dataset_plays_through_the_real_turn(name: str) -> None:
    """Each scripted case through ``AIService.chat``: its tools run, its
    trace is kept, and every assertion holds. ``make evals-ci``."""
    report = await runner.run_dataset(name, scripted=True)

    assert not report.failures, [f.error_message for f in report.failures]
    assert report.cases
    for case in report.cases:
        assert all(r.value for r in case.assertions.values()), case.name
