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
CHECK = "parts.reads-in-queries"
TOUCHED = "### What this change touches\n\n- **Parts:** `service:notes`\n"


def _finding(*evidence: str) -> Finding:
    return Finding(
        check=CHECK,
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
            Note(check=CHECK, said="This read belongs in queries.py."),
            Note(check="parts.invented", said="An invented finding."),
        ),
        opinion="The module could be split.",
    )
    text = pattern_review.markdown(fresh, said, touched=TOUCHED)
    assert f"`{STORE}:2`" in text and "Reads live in queries" in text
    assert "This read belongs in queries.py." in text
    assert "An invented finding." not in text  # not a finding's rule: not listed
    assert text.index(pattern_review.OPINION) < text.index("The module could be split.")
    assert text.startswith(pattern_review.MARKER)


async def test_nothing_new_gets_her_seal_and_asks_no_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*_: object) -> None:
        raise AssertionError("no model call without a new finding")

    monkeypatch.setattr(pattern_review, "_ask", never)
    text = await pattern_review.review([], touched="")
    assert "**Clear.**" in text
    assert pattern_review.SEAL in text


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
            notes=(Note(check=CHECK, said="Move it into queries.py."),),
        )

    monkeypatch.setattr(pattern_review, "_ask", ask)
    first = await pattern_review.review(fresh, "", commit="aaaaaaa1")
    second = await pattern_review.review([], "", previous=first, commit="bbbbbbb2")
    third = await pattern_review.review(fresh, "", previous=second, commit="ccccccc3")

    current, _, earlier = third.partition("#### Earlier reviews")
    assert "review of `ccccccc`" in current
    assert earlier.index("review of `bbbbbbb`") < earlier.index("review of `aaaaaaa`")
    assert pattern_review.SEAL in earlier  # the clean one, kept
    assert earlier.count("Move it into queries.py.") == 1  # the first, as written
    assert third.startswith(pattern_review.MARKER)


def _spots(tmp_path: Path, count: int) -> list:  # type: ignore[type-arg]
    lines = "".join(f"x{i} = await session.exec(q)\n" for i in range(count))
    write_tree(tmp_path, {STORE: lines})
    places = (f"{STORE}:{i}" for i in range(1, count + 1))
    return new_spots([_finding(*places)], source_index.at(tmp_path))


def test_a_rule_is_said_once_however_many_places_break_it(tmp_path: Path) -> None:
    """Five places breaking one rule: its title, its check and her note on
    it once, each place listed under it."""
    said = Review(
        summary="Reads moved.", notes=(Note(check=CHECK, said="Batch them."),)
    )
    text = pattern_review.markdown(_spots(tmp_path, 5), said, touched="")
    assert text.count("Reads live in queries") == 1
    assert text.count(f"`{CHECK}`") == 1
    assert text.count("Batch them.") == 1
    assert all(f"`{STORE}:{i}`" in text for i in range(1, 6))


def test_a_few_places_show_and_many_fold(tmp_path: Path) -> None:
    said = Review(summary="Reads.")
    few = pattern_review.markdown(_spots(tmp_path, pattern_review.SHOWN), said, "")
    many = pattern_review.markdown(_spots(tmp_path, pattern_review.SHOWN + 1), said, "")
    assert "<details>" not in few
    assert f"<summary>{pattern_review.SHOWN + 1} places</summary>" in many


def test_what_the_change_touches_is_folded_away(fresh: list) -> None:  # type: ignore[type-arg]
    """Her words and the findings are what is read; what the change touches
    is there to open, under its own heading, never said twice."""
    text = pattern_review.markdown(fresh, Review(summary="Fine."), touched=TOUCHED)
    assert "<summary>What this change touches</summary>" in text
    assert "### What this change touches" not in text
    assert text.count("`service:notes`") == 1


def test_her_verdict_leads_and_is_the_checks_not_hers(
    fresh: list,  # type: ignore[type-arg]
) -> None:
    """Blocked or clear is decided by the rules (``Finding.blocking``), said
    first; what she writes cannot soften it."""
    said = Review(summary="Nothing to worry about.", notes=())
    text = pattern_review.markdown(fresh, said, touched="")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("<!--")]
    assert lines[1].startswith("**Blocked.** 1 new place breaks")
    assert "· blocks" in text
    advisory = [
        s._replace(finding=s.finding.model_copy(update={"severity": "warn"}))
        for s in fresh
    ]
    clear = pattern_review.markdown(advisory, said, touched="")
    assert "**Clear.**" in clear and "· advisory" in clear


async def test_her_review_stands_when_the_model_does_not_answer(
    fresh: list,  # type: ignore[type-arg]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict and every place, in the rules' own words: a model down
    never leaves a change unreviewed."""

    async def down(facts: str) -> Review:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(pattern_review, "_ask", down)
    text = await pattern_review.review(fresh, touched="")
    assert "**Blocked.**" in text and f"`{STORE}:2`" in text
    assert "One place, batched." in text
    assert pattern_review.UNSAID in text
