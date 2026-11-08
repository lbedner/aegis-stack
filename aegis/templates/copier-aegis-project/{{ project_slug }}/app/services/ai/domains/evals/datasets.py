"""Datasets: ``evals/<name>.yaml``, each case a message and what its turn
should do. Pydantic Evals reads the file; a case may use its built-in
evaluators (``Contains``, ``LLMJudge``) and the trace ones here."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Dataset

from app.core.source_index import ROOT

from .evaluators import EVALUATORS
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


def load(name: str, directory: Path = EVALS_DIR) -> EvalDataset:
    """``<directory>/<name>.yaml``, its cases checked against ``CaseInput``."""
    return EvalDataset.from_file(
        directory / f"{name}.yaml", custom_evaluator_types=EVALUATORS
    )
