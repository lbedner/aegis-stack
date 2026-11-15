"""The ``evals`` tool: what whoever drives the loop reads. The datasets and
the latest runs, one run's failing cases and why each failed, two runs
compared. An admin's, as the evals are everywhere; what it reads is changed
by proposing (``changes``), never here."""

from datetime import datetime

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.figures import FIGURES, absent
from app.core.tools import Refused, register_tool
from app.services.ai.models.evals import EvalCase, EvalRun, EvalScore

from . import queries
from .datasets import DatasetSummary, UnknownDatasetError, describe, describe_all
from .evaluators import called

# The most runs one answer lists, newest first.
RUNS = 20


class RunRead(BaseModel):
    """A kept run: what it ran, on what, and how it went."""

    model_config = FIGURES

    id: int
    dataset: str
    model: str | None = absent()
    build: str | None = absent()
    started_at: datetime
    cases: int
    passed: int
    cost: float
    trigger: str
    note: str | None = absent()


class Verdict(BaseModel):
    """One evaluator on a case: the rule it scored, and why it said no."""

    model_config = FIGURES

    evaluator: str
    rule: str | None = absent()
    value: float
    passed: bool | None = absent()
    reason: str | None = absent()


class FailedCase(BaseModel):
    """A case that failed: what it asked, what came back, the calls its
    turn made, and each verdict that did not pass (none where it never
    ran: ``error`` says why)."""

    model_config = FIGURES

    name: str
    asked: str | None = absent()
    answered: str | None = absent()
    error: str | None = absent()
    called: str
    verdicts: list[Verdict]


class Kept(BaseModel):
    """The datasets, each case and what it checks in words, and the latest
    runs, newest first."""

    model_config = FIGURES

    datasets: list[DatasetSummary]
    runs: list[RunRead]


class RunDetail(BaseModel):
    """A run, the cases it failed and the names of those it passed."""

    model_config = FIGURES

    run: RunRead
    failed: list[FailedCase]
    passed: list[str]


def _run(row: EvalRun) -> RunRead:
    assert row.id is not None
    return RunRead(
        id=row.id,
        dataset=row.dataset,
        model=row.model_id,
        build=row.build,
        started_at=row.started_at,
        cases=row.cases,
        passed=row.passed,
        cost=row.total_cost,
        trigger=row.trigger,
        note=row.note,
    )


def _failed(case: EvalCase, scores: list[EvalScore]) -> FailedCase:
    return FailedCase(
        name=case.name,
        asked=case.inputs.get("message"),
        answered=case.output,
        error=case.error,
        called=called(case.tool_calls),
        verdicts=[Verdict.model_validate(s, from_attributes=True) for s in scores],
    )


async def kept(session: AsyncSession, dataset: str | None = None) -> Kept:
    """Every dataset and the latest runs, or ``dataset`` and its own.
    ``UnknownDatasetError`` for a dataset there is none of."""
    found = [await describe(session, dataset)] if dataset else await describe_all(session)
    runs = await queries.runs(session, dataset, RUNS)
    return Kept(datasets=found, runs=[_run(row) for row in runs])


async def run_detail(session: AsyncSession, run_id: int) -> RunDetail | None:
    """Run ``run_id`` and why its failures failed, in three queries; None
    for no such run."""
    row = await queries.run(session, run_id)
    if row is None:
        return None
    by_case = await queries.scores_by_case(session, run_id, failed=True)
    cases = await queries.cases(session, run_id)
    return RunDetail(
        run=_run(row),
        failed=[_failed(c, by_case.get(c.id, [])) for c in cases if not c.passed],
        passed=[c.name for c in cases if c.passed],
    )


async def evals(
    dataset: str | None = None, run: int | None = None, against: int | None = None
) -> Kept | RunDetail | queries.Comparison | Refused:
    """The evals: what a turn should do, as cases, and how each run of them
    went. No argument: every dataset (each case, what it asks and checks)
    and the latest runs. ``dataset``: that one and its runs. ``run`` (an
    id): the cases it failed, each with what was asked, what came back, the
    calls made and why each check said no. ``run`` and ``against`` (an
    earlier run's id): the cases that changed between the two, flips first.
    A case is added and a run started by proposing ``eval_dataset.add_case``
    or ``eval_run.start`` (the ``propose`` tool, where granted); a person
    approves it."""
    async with get_async_session() as session:
        if run is None:
            try:
                return await kept(session, dataset)
            except UnknownDatasetError as exc:
                return Refused(error=str(exc))
        if against is not None:
            return await queries.compare(session, against, run)
        return await run_detail(session, run) or Refused(error=f"No run {run}")


register_tool(
    "evals",
    evals,
    description="The eval datasets and runs: what a run failed and why, two runs compared",
    effect="read",
    doing="Reading the evals",
    admin=True,
)
