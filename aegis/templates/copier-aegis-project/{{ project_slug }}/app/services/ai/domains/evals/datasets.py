"""Datasets: ``evals/<name>.yaml``, each case a message and what its turn
should do. Pydantic Evals reads the file; a case may use its built-in
evaluators (``Contains``, ``LLMJudge``) and the trace ones here."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Dataset

from app.core.source_index import ROOT

from .evaluators import EVALUATORS, explain
from .script import Step

EVALS_DIR = ROOT / "evals"


class CaseInput(BaseModel):
    """What a case asks: a message, to an agent (the default when unset),
    and the ``script`` its turn plays in CI."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str
    agent: str | None = None
    script: list[Step] = []


EvalDataset = Dataset[CaseInput, str, None]


class UnknownDatasetError(LookupError, ValueError):
    """A name that is not a dataset under ``evals/``."""


def names(directory: Path = EVALS_DIR) -> list[str]:
    """Every dataset under ``directory``, by the name ``load`` takes."""
    return sorted(path.stem for path in directory.glob("*.yaml"))


def dataset_path(name: str, directory: Path = EVALS_DIR) -> Path:
    """``<directory>/<name>.yaml``, for a name ``names`` lists only: never
    a file outside it (``../``)."""
    known = names(directory)
    if name not in known:
        there = ", ".join(known) or "none"
        raise UnknownDatasetError(f"No dataset {name!r} under evals/ (there: {there})")
    return directory / f"{name}.yaml"


def load(name: str, directory: Path = EVALS_DIR) -> EvalDataset:
    """``name``'s file, its cases checked against ``CaseInput``."""
    return EvalDataset.from_file(
        dataset_path(name, directory), custom_evaluator_types=EVALUATORS
    )


class CaseSummary(BaseModel):
    """A case read before a run: what it asks, of which agent (the default
    when unset), and what it checks, in words."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    message: str
    agent: str | None
    checks: list[str]


class DatasetSummary(BaseModel):
    """A dataset read before a run: what its leading comment says it is,
    and its cases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    about: str
    cases: list[CaseSummary]


def _about(path: Path) -> str:
    """The file's leading comment, up to its first blank comment line."""
    said: list[str] = []
    for line in path.read_text().splitlines():
        if not line.startswith("#") or not line.strip("# "):
            break
        said.append(line.strip("# "))
    return " ".join(said)


def describe(name: str, directory: Path = EVALS_DIR) -> DatasetSummary:
    """``name`` as ``load`` reads it, each case's checks its own and then
    the dataset's, which hold for every case."""
    dataset = load(name, directory)
    shared = [explain(e) for e in dataset.evaluators]
    return DatasetSummary(
        name=name,
        about=_about(dataset_path(name, directory)),
        cases=[
            CaseSummary(
                name=case.name or "",
                message=case.inputs.message,
                agent=case.inputs.agent,
                checks=[*(explain(e) for e in case.evaluators), *shared],
            )
            for case in dataset.cases
        ],
    )
