"""A dataset read before it is run: what its leading comment says it is,
and each case's message, agent and checks in words."""

from pathlib import Path

import pytest

from app.services.ai.domains.evals import datasets
from app.services.ai.domains.evals.datasets import (
    UnknownDatasetError,
    describe,
    describe_all,
    load,
    remove,
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
        'says "letter"',
        'never says "sorry"',
    ]
    assert second.checks == ["never calls delete", 'never says "sorry"']
    assert first.why is None


def test_a_case_says_why_it_is_there(tmp_path: Path) -> None:
    why = "    metadata:\n      why: a letter is read, not guessed\n"
    marked = DATASET.replace("    evaluators:\n", why + "    evaluators:\n", 1)
    (tmp_path / "mini.yaml").write_text(marked)

    first, second = describe("mini", tmp_path).cases

    assert (first.why, second.why) == ("a letter is read, not guessed", None)


def test_only_a_dataset_under_the_folder_is_read(tmp_path: Path) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    (tmp_path.parent / "outside.yaml").write_text(DATASET)

    for name in ("nope", f"../{tmp_path.parent.name}/outside", "../outside"):
        with pytest.raises(UnknownDatasetError):
            load(name, tmp_path)


def test_a_dataset_is_removed_by_name_and_no_other_file_is(tmp_path: Path) -> None:
    (tmp_path / "mini.yaml").write_text(DATASET)
    (tmp_path / "notes.txt").write_text("kept")

    for name in ("nope", "../mini", "notes"):
        with pytest.raises(UnknownDatasetError):
            remove(name, tmp_path)
    remove("mini", tmp_path)

    assert [p.name for p in tmp_path.iterdir()] == ["notes.txt"]


def test_a_dataset_gone_meanwhile_is_unknown_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleted twice at once (two tabs): the second finds no file."""
    (tmp_path / "mini.yaml").write_text(DATASET)
    monkeypatch.setattr(datasets, "dataset_path", lambda name, directory: tmp_path / "gone.yaml")

    with pytest.raises(UnknownDatasetError):
        remove("mini", tmp_path)


def test_a_file_that_cannot_be_read_hides_no_other(tmp_path: Path) -> None:
    """One bad file is listed with why it cannot be read, naming it; the
    rest are read as ever."""
    (tmp_path / "mini.yaml").write_text(DATASET)
    (tmp_path / "torn.yaml").write_text("cases: [")
    (tmp_path / "wrong.yaml").write_text("cases:\n  - name: x\n    inputs: {nope: 1}\n")

    mini, torn, wrong = describe_all(tmp_path)

    assert len(mini.cases) == 2
    assert "torn.yaml" in torn.about and torn.cases == []
    assert wrong.about.startswith("Cannot be read") and wrong.cases == []
    with pytest.raises(ValueError, match="torn.yaml"):
        load("torn", tmp_path)
