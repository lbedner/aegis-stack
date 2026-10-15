"""The Query editor's tabs (static/js/sql.js, run in node): kept in this
browser, started afresh when nothing (or garbage) is kept, and a table's
statement opened once. What it marks as wrong is sql-read.js's
(test_sql_read.py)."""

from pathlib import Path

from tests.web.node import run

SQL_JS = Path("app/components/web_frontend/static/js/sql.js")

TABS = """
const store = {};
global.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
const c = require(SQL_JS);
"""


def test_the_tabs_start_afresh_and_a_table_opens_one_once() -> None:
    """Nothing kept (or kept garbled): one empty tab. A table's statement
    opens a tab, named for it; asked again, the same tab."""
    script = (
        TABS
        + """
const fresh = c.load();
localStorage.setItem('aegis-sql-tabs', '{oops');
const garbled = c.load();
const book = { tabs: [{ id: 4, name: 'mine', sql: 'SELECT 1' }], active: 4 };
c.seeded(book, 'SELECT * FROM org', 'org');
const first = JSON.parse(JSON.stringify(book));
c.seeded(book, 'SELECT * FROM org', 'org');
console.log(JSON.stringify({ fresh, garbled, first, again: book }));
"""
    )
    found = run(script, SQL_JS=SQL_JS)
    empty = {"tabs": [{"id": 1, "name": "Query 1", "sql": ""}], "active": 1}
    assert found["fresh"] == empty and found["garbled"] == empty
    assert found["first"]["active"] == 5
    assert found["first"]["tabs"][-1] == {
        "id": 5,
        "name": "org",
        "sql": "SELECT * FROM org",
    }
    assert found["again"] == found["first"]
