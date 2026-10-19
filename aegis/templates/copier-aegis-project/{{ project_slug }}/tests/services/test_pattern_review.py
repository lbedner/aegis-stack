"""``patterns review``: Illiana's write-up of a change's new findings."""

from pathlib import Path

import pytest

from app.core import source_index
from app.services.system import pattern_review
from app.services.system.pattern_check import new_spots
from app.services.system.pattern_findings import Finding
from app.services.system.pattern_review import Note, Review
from tests._files import write_tree

STORE = "app/services/notes/store.py"


def _finding(*evidence: str) -> Finding:
    return Finding(
        check="parts.reads-in-queries",
        subject="service:notes",
        severity="error",
        title="Reads live in queries",
        why="One place, batched.",
        evidence=evidence,
        action="Move the read into queries.py.",
        fingerprint="f",
    )


@pytest.fixture
def fresh(tmp_path: Path) -> list:  # type: ignore[type-arg]
    write_tree(tmp_path, {STORE: "a = 1\nb = await session.exec(q)\n"})
    return new_spots([_finding(f"{STORE}:2")], source_index.at(tmp_path))


def test_every_finding_is_listed_whatever_she_says(fresh: list) -> None:  # type: ignore[type-arg]
    said = Review(
        summary="One read sits outside queries.",
        notes=(
            Note(place=f"{STORE}:2", said="This read belongs in queries.py."),
            Note(place="app/elsewhere.py:9", said="An invented finding."),
        ),
        opinion="The module could be split.",
    )
    text = pattern_review.markdown(fresh, said, touched="### Touches\n")
    assert f"`{STORE}:2`" in text and "Reads live in queries" in text
    assert "This read belongs in queries.py." in text
    assert "app/elsewhere.py" not in text  # not a finding: not listed
    assert "Opinion" in text and "The module could be split." in text
    assert text.startswith(pattern_review.MARKER)


async def test_nothing_new_asks_no_one(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(*_: object) -> None:
        raise AssertionError("no model call without a new finding")

    monkeypatch.setattr(pattern_review, "_ask", never)
    text = await pattern_review.review([], touched="")
    assert pattern_review.NOTHING in text


async def test_she_is_asked_with_the_facts(
    fresh: list,  # type: ignore[type-arg]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    async def ask(facts: str) -> Review:
        asked.append(facts)
        return Review(summary="Looks contained.", notes=())

    monkeypatch.setattr(pattern_review, "_ask", ask)
    text = await pattern_review.review(fresh, touched="")
    assert f"{STORE}:2" in asked[0] and "reads-in-queries" in asked[0]
    assert "Looks contained." in text
    assert "One place, batched." in text  # her silence on it: the rule's why


async def test_a_long_list_is_capped_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first run, with no baseline, can bring hundreds: she reads and the
    comment lists the first ``MOST_LISTED``, and says how many more."""
    lines = "".join(f"x{i} = await session.exec(q)\n" for i in range(60))
    write_tree(tmp_path, {STORE: lines})
    many = new_spots(
        [_finding(*(f"{STORE}:{i}" for i in range(1, 61)))], source_index.at(tmp_path)
    )
    asked: list[str] = []

    async def ask(facts: str) -> Review:
        asked.append(facts)
        return Review(summary="Many reads.")

    monkeypatch.setattr(pattern_review, "_ask", ask)
    text = await pattern_review.review(many, touched="")
    assert f"{STORE}:{pattern_review.MOST_LISTED}`" in text
    assert f"{STORE}:{pattern_review.MOST_LISTED + 1}`" not in text
    assert f'{STORE}:{pattern_review.MOST_LISTED + 1}"' not in asked[0]
    assert f"and {60 - pattern_review.MOST_LISTED} more" in text


async def test_findings_an_earlier_review_covered_are_not_asked_again(
    fresh: list,  # type: ignore[type-arg]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each push of a pull request runs it: the same findings, no call and
    no rewrite of its comment."""

    async def ask(_: str) -> Review:
        return Review(summary="One read outside queries.")

    monkeypatch.setattr(pattern_review, "_ask", ask)
    first = await pattern_review.review(fresh, "", commit="aaaaaaa1")

    async def never(*_: object) -> None:
        raise AssertionError("no model call for findings already reviewed")

    monkeypatch.setattr(pattern_review, "_ask", never)
    assert await pattern_review.review(fresh, "", previous=first, commit="b") == ""


async def test_each_review_keeps_the_ones_before_it(
    fresh: list,  # type: ignore[type-arg]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One comment, edited on each push, still tells the sequence: the
    latest review on top, every earlier one below it by the commit it
    reviewed, newest first, as it was written."""

    async def ask(_: str) -> Review:
        return Review(
            summary="One read outside queries.",
            notes=(Note(place=f"{STORE}:2", said="Move it into queries.py."),),
        )

    monkeypatch.setattr(pattern_review, "_ask", ask)
    first = await pattern_review.review(fresh, "", commit="aaaaaaa1")
    second = await pattern_review.review([], "", previous=first, commit="bbbbbbb2")
    third = await pattern_review.review(fresh, "", previous=second, commit="ccccccc3")

    current, _, earlier = third.partition("#### Earlier reviews")
    assert "review of `ccccccc`" in current
    assert earlier.index("review of `bbbbbbb`") < earlier.index("review of `aaaaaaa`")
    assert pattern_review.NOTHING in earlier  # the clean one, kept
    assert earlier.count("Move it into queries.py.") == 1  # the first, as written
    assert third.startswith(pattern_review.MARKER)
