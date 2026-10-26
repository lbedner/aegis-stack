"""``patterns check``: new findings against the known debt."""

from pathlib import Path

from app.core import source_index
from app.services.system.pattern_check import check
from app.services.system.pattern_findings import Finding
from tests._files import write_tree

STORE = "app/services/notes/store.py"
READ = "    return await session.exec(q)\n"


def _finding(*evidence: str, severity: str = "error", gated: bool = False) -> Finding:
    return Finding(
        check="parts.reads-in-queries",
        subject="service:notes",
        severity=severity,  # type: ignore[arg-type]
        gated=gated,
        title="Reads live in queries",
        why="One place, batched.",
        evidence=evidence,
        action="Move the read into queries.py.",
        fingerprint="f",
    )


def _at(root: Path) -> source_index.Index:
    return source_index.at(root)


def test_known_debt_stays_known_when_code_moves_above_it(tmp_path: Path) -> None:
    write_tree(tmp_path, {STORE: "async def all(session):\n" + READ})
    check([_finding(f"{STORE}:2")], _at(tmp_path), update=True)
    write_tree(tmp_path, {STORE: "import x\n\nasync def all(session):\n" + READ})
    out, code = check([_finding(f"{STORE}:4")], _at(tmp_path))
    assert code == 0 and STORE not in out
    write_tree(tmp_path, {STORE: "async def all(session):\n" + READ + "    q()\n"})
    out, _ = check([_finding(f"{STORE}:2", f"{STORE}:3")], _at(tmp_path))
    assert f"{STORE}:3" in out and f"{STORE}:2" not in out


def test_the_baseline_only_shrinks(tmp_path: Path) -> None:
    write_tree(tmp_path, {STORE: "a = 1\nb = 2\n"})
    check([_finding(f"{STORE}:1")], _at(tmp_path), update=True)
    check([_finding(f"{STORE}:2")], _at(tmp_path), update=True)
    out, _ = check([_finding(f"{STORE}:2")], _at(tmp_path))
    assert f"{STORE}:2" in out  # never folded into the known debt


def test_advisory_unless_strict_and_strict_only_on_an_error(tmp_path: Path) -> None:
    write_tree(tmp_path, {STORE: READ})
    index = _at(tmp_path)
    assert check([_finding(f"{STORE}:1")], index)[1] == 0
    assert check([_finding(f"{STORE}:1")], index, strict=True)[1] == 1
    warn = _finding(f"{STORE}:1", severity="warn")
    assert check([warn], index, strict=True)[1] == 0


def test_a_gated_rule_blocks_a_new_place_while_its_debt_stands(
    tmp_path: Path,
) -> None:
    """Advisory on the page (a warning, its known debt allowed), yet a new
    place breaking it blocks the change under ``strict``."""
    write_tree(tmp_path, {STORE: READ + READ})
    index = _at(tmp_path)
    check([_finding(f"{STORE}:1", severity="warn", gated=True)], index, update=True)
    known = _finding(f"{STORE}:1", severity="warn", gated=True)
    assert check([known], index, strict=True)[1] == 0
    fresh = _finding(f"{STORE}:1", f"{STORE}:2", severity="warn", gated=True)
    out, code = check([fresh], index, strict=True)
    assert code == 1
    assert out.splitlines()[-1].startswith("Illiana: blocked. 1 new place breaks")


def test_illiana_says_her_verdict_last(tmp_path: Path) -> None:
    write_tree(tmp_path, {STORE: READ})
    warn = _finding(f"{STORE}:1", severity="warn")
    out, _ = check([warn], _at(tmp_path))
    assert out.splitlines()[-1].startswith("Illiana: clear.")


def test_under_github_actions_each_is_annotated_and_summarised(
    tmp_path: Path,
) -> None:
    write_tree(tmp_path, {STORE: READ})
    summary = tmp_path / "summary.md"
    env = {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)}
    found = [_finding(f"{STORE}:1"), _finding(f"{STORE}:1", severity="warn")]
    out, _ = check(found, _at(tmp_path), env=env, touched="### Touches\n")
    blocking, advisory = out.splitlines()[:2]
    assert advisory.startswith("::warning ")
    assert blocking == (
        f"::error file={STORE},line=1,title=Illiana%3A Reads live in queries::"
        f"{STORE}:1 parts.reads-in-queries: One place, batched. "
        "Move the read into queries.py."
    )
    written = summary.read_text()
    assert written.startswith("### Touches")
    assert "### Illiana: blocked" in written
    assert f"- **Blocks** `{STORE}:1`" in written
    assert f"- Advisory `{STORE}:1`" in written


def test_the_new_places_are_written_for_a_reviewer_keyed_as_the_baseline_knows_them(
    tmp_path: Path,
) -> None:
    """``PATTERNS_FOUND`` names a file the new places are written to, each
    with the key the baseline knows it by: what her review threads are
    keyed on (aegis-stack's ``scripts/illiana_threads.py``)."""
    import json

    write_tree(tmp_path, {STORE: READ})
    written = tmp_path / "found.json"
    found = [_finding(f"{STORE}:1"), _finding(f"{STORE}:1", severity="warn")]

    check(found, _at(tmp_path), env={"PATTERNS_FOUND": str(written)})
    check(found[:1], _at(tmp_path), update=True)
    known = json.loads((tmp_path / ".patterns-baseline.json").read_text())["known"]

    blocking, advisory = json.loads(written.read_text())["found"]
    assert blocking == {
        "path": STORE,
        "line": 1,
        "check": "parts.reads-in-queries",
        "subject": "service:notes",
        "title": "Reads live in queries",
        "why": "One place, batched.",
        "action": "Move the read into queries.py.",
        "blocking": True,
        "key": known[0],
    }
    assert advisory["blocking"] is False
