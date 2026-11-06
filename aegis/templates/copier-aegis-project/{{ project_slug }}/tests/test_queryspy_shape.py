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


@pytest.mark.parametrize(
    ("plain", "qualified"),
    [
        (
            "SELECT t.id FROM t WHERE t.owner_id = :owner_id_1 ORDER BY t.at DESC",
            "SELECT s.t.id FROM s.t WHERE s.t.owner_id = :owner_id_1 ORDER BY s.t.at DESC",
        ),
        (
            "SELECT t.id FROM t JOIN u ON u.id = t.user_id",
            "SELECT s.t.id FROM s.t JOIN s.u ON s.u.id = s.t.user_id",
        ),
        (
            "UPDATE t SET name=:name WHERE t.id = :id_1",
            "UPDATE s.t SET name=:name WHERE s.t.id = :id_1",
        ),
        ("INSERT INTO t (id) VALUES (:id)", "INSERT INTO s.t (id) VALUES (:id)"),
        ('SELECT "user".id FROM "user"', 'SELECT s."user".id FROM s."user"'),
    ],
)
def test_a_schema_is_no_part_of_the_shape(plain: str, qualified: str) -> None:
    """The engine decides the schema: the shipped baseline is recorded on
    SQLite, which has none, and a Postgres project renders one."""
    assert statement_shape(qualified) == statement_shape(plain)


def test_a_table_and_its_column_are_not_a_schema() -> None:
    sql = "SELECT 1 FROM t WHERE t.owner_id = :owner_id_1"
    assert "t.owner_id" in statement_shape(sql)
