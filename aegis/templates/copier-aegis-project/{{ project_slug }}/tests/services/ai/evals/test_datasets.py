"""A dataset read before it is run: what its leading comment says it is,
and each case's message, agent and checks in words."""

from pathlib import Path

import pytest

from app.services.ai.domains.evals.datasets import (
    UnknownDatasetError,
    describe,
    load,
)

from ._mini import DATASET


def test_a_dataset_says_what_it_is_and_what_each_case_checks(tmp_path: Path) -> None:
    about = "# Reads what it is given.\n# Two cases.\n#\n# How to add one.\n"
    shared = "evaluators:\n  - AnswerAvoids:\n      terms: [sorry]\n"
    (tmp_path / "mini.yaml").write_text(about + DATASET + shared)

    found = describe("mini", tmp_path)

    assert found.name == "mini" and found.about == "Reads what it is given. Two cases."
    first, second = found.cases
    assert first.name == "reads the paper"
    assert first.message == "what does the letter say?" and first.agent is None
    assert first.checks == [
        "calls paper once",
        "Contains(value='letter')",
        'never says "sorry"',
    ]
    assert second.checks == ["never calls delete", 'never says "sorry"']


def test_only_a_dataset_under_the_folder_is_read(tmp_path: Path) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    (tmp_path.parent / "outside.yaml").write_text(DATASET)

    for name in ("nope", f"../{tmp_path.parent.name}/outside", "../outside"):
        with pytest.raises(UnknownDatasetError):
            load(name, tmp_path)
