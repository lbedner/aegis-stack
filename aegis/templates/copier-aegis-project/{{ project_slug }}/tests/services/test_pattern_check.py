"""``patterns check``: new findings against the known debt."""

from pathlib import Path

from app.core import source_index
from app.services.system.pattern_check import check
from app.services.system.pattern_findings import Finding
from tests._files import write_tree

STORE = "app/services/notes/store.py"
READ = "    return await session.exec(q)\n"


def _finding(*evidence: str, severity: str = "error") -> Finding:
    return Finding(
        check="parts.reads-in-queries",
        subject="service:notes",
        severity=severity,  # type: ignore[arg-type]
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


def test_under_github_actions_each_is_annotated_and_summarised(
    tmp_path: Path,
) -> None:
    write_tree(tmp_path, {STORE: READ})
    summary = tmp_path / "summary.md"
    env = {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)}
    found = [_finding(f"{STORE}:1")]
    out, _ = check(found, _at(tmp_path), env=env, touched="### Touches\n")
    assert out.splitlines()[0] == (
        f"::warning file={STORE},line=1,title=parts.reads-in-queries::"
        f"{STORE}:1 parts.reads-in-queries: One place, batched. "
        "Move the read into queries.py."
    )
    written = summary.read_text()
    assert written.startswith("### Touches")
    assert f"`{STORE}:1`" in written
