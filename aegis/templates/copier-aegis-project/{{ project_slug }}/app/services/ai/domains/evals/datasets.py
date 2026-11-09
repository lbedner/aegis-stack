"""Datasets: ``evals/<name>.yaml``, each case a message and what its turn
should do. Pydantic Evals reads the file; a case may use its built-in
evaluators (``Contains``, ``LLMJudge``) and the trace ones here."""

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Dataset
import yaml

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


class CaseMeta(BaseModel):
    """What a case says of itself: ``why`` it is there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    why: str | None = None


EvalDataset = Dataset[CaseInput, str, CaseMeta]


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


def remove(name: str, directory: Path = EVALS_DIR) -> None:
    """Delete ``name``'s file (``UnknownDatasetError`` when there is none,
    or it went meanwhile); its kept runs stay."""
    try:
        dataset_path(name, directory).unlink()
    except FileNotFoundError:
        raise UnknownDatasetError(f"No dataset {name!r} under evals/") from None


def fingerprint(name: str, directory: Path = EVALS_DIR) -> str:
    """``name``'s file as it is now: the SHA-256 of its bytes."""
    return hashlib.sha256(dataset_path(name, directory).read_bytes()).hexdigest()


def load(name: str, directory: Path = EVALS_DIR) -> EvalDataset:
    """``name``'s file, its cases checked against ``CaseInput``; ValueError,
    naming the file, for one that cannot be read."""
    path = dataset_path(name, directory)
    try:
        return EvalDataset.from_file(path, custom_evaluator_types=EVALUATORS)
    except yaml.YAMLError as exc:
        raise ValueError(f"evals/{path.name} is not YAML: {exc}") from exc


def without(dataset: EvalDataset, kinds: tuple[type, ...]) -> None:
    """Drop every check of ``kinds`` from ``dataset`` and its cases."""
    dataset.evaluators = [e for e in dataset.evaluators if not isinstance(e, kinds)]
    for case in dataset.cases:
        case.evaluators = [e for e in case.evaluators if not isinstance(e, kinds)]


class CaseSummary(BaseModel):
    """A case read before a run: what it asks, of which agent (the default
    when unset), and what it checks, in words."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    why: str | None = None
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
                why=case.metadata and case.metadata.why,
                message=case.inputs.message,
                agent=case.inputs.agent,
                checks=[*(explain(e) for e in case.evaluators), *shared],
            )
            for case in dataset.cases
        ],
    )


def describe_all(directory: Path = EVALS_DIR) -> list[DatasetSummary]:
    """Every dataset under ``directory``, as ``describe`` reads it. One
    that cannot be read says why where its ``about`` goes, with no cases:
    a bad file hides no other, and can still be opened and deleted."""
    found: list[DatasetSummary] = []
    for name in names(directory):
        try:
            found.append(describe(name, directory))
        except ValueError as exc:
            found.append(DatasetSummary(name=name, about=f"Cannot be read: {exc}", cases=[]))
    return found
