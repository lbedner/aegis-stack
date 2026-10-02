"""A repeated statement is known debt by its shape, not its text.

queryspy names a repeated statement by its whole SQL, select list included,
so adding a column to a table renamed every SELECT on it: the baseline read
as all new, and the only way back was rewriting it, which hides whether
anything really changed.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from queryspy import _baseline, pytest_plugin
from queryspy._baseline import BaselineEntry
from queryspy._detect import Finding
from queryspy._frames import AppFrame

from tests import _queryspy_shape
from tests._queryspy_shape import shaped, statement_shape

NARROW = "SELECT t.id, t.name FROM t WHERE t.owner_id = :owner_id_1"
WIDER = "SELECT t.id, t.name, t.deleted_at FROM t WHERE t.owner_id = :owner_id_1"
OTHER_WHERE = "SELECT t.id, t.name FROM t WHERE t.budget_id = :budget_id_1"


def _entry(label: str, kind: str = "repeated_statement") -> BaselineEntry:
    return BaselineEntry(kind=kind, label=label, file="app/x.py", function="read")


def _finding(sql: str) -> Finding:
    """A repeated statement as queryspy reports one."""
    frame = AppFrame(filename="app/x.py", lineno=12, function="read")
    return Finding(kind="repeated_statement", label=sql, count=2, sql=sql, frame=frame)


def test_a_new_column_keeps_the_shape() -> None:
    assert statement_shape(NARROW) == statement_shape(WIDER)
    assert shaped(_entry(NARROW)) == shaped(_entry(WIDER))


def test_a_different_query_is_a_different_shape() -> None:
    assert statement_shape(NARROW) != statement_shape(OTHER_WHERE)


def test_distinct_is_part_of_the_shape() -> None:
    """DISTINCT is not a selected column: dropping it gave ``SELECT t.id``
    and ``SELECT DISTINCT t.id`` one identity."""
    distinct = "SELECT DISTINCT t.id FROM t WHERE t.owner_id = :owner_id_1"

    assert statement_shape(distinct) == (
        "SELECT DISTINCT ... FROM t WHERE t.owner_id = :owner_id_1"
    )
    assert statement_shape(distinct) != statement_shape(NARROW)


def test_the_shape_still_reads_as_sql() -> None:
    assert statement_shape(WIDER) == "SELECT ... FROM t WHERE t.owner_id = :owner_id_1"


def test_only_statements_are_reshaped() -> None:
    """A lazy or column load is named by its model, which a column does
    not change."""
    column_load = _entry("Account", kind="column_load")

    assert shaped(column_load) == column_load


def test_queryspy_compares_stales_and_saves_by_shape(tmp_path: Path) -> None:
    """queryspy's own split, stale check and save, run on a statement that
    gained a column since its entry was written: known, not stale, and
    written once. A queryspy that stops naming findings through
    ``_baseline.entry_for`` fails here rather than in a hundred tests."""
    narrow, wider = _finding(NARROW), _finding(WIDER)
    baseline = {_baseline.entry_for(narrow)}

    assert _baseline.split([wider], baseline) == ([], [wider])
    assert _baseline.stale(baseline, [wider]) == []
    path = tmp_path / "baseline.json"
    assert _baseline.save(path, [narrow, wider], version="test") == 1
    (written,) = json.loads(path.read_text())["entries"]
    assert written["label"] == statement_shape(WIDER)


def test_a_baseline_written_in_full_sql_is_read_by_shape() -> None:
    """The stash queryspy loads at configure time is reshaped, so a file
    written before shapes, or by hand, still matches."""
    stash = pytest.Stash()
    stash[pytest_plugin._BASELINE] = {_entry(WIDER)}

    _queryspy_shape.shape_loaded_baseline(SimpleNamespace(stash=stash))  # type: ignore[arg-type]

    assert stash[pytest_plugin._BASELINE] == {shaped(_entry(NARROW))}
