"""What the Query editor marks as wrong as you type (static/js/sql-read.js,
run in node), with no request: its own grammar's errors, a quote left
open, a table the schema lacks; and the columns it offers: the tables the
statement reads, only.

The tokens are the SQL grammar's own (``sql_tokens.json``: each statement
parsed by @codemirror/lang-sql and read by ``tokensOf``, as the editor does;
regenerate it with ``sql_tokens.cjs`` when the grammar or ``tokensOf``
changes)."""

import json
from pathlib import Path
from typing import Any

from tests.web.node import call

SQL_READ = Path("app/components/web_frontend/static/js/sql-read.js")
TOKENS = json.loads((Path(__file__).parent / "sql_tokens.json").read_text())
SCHEMA = {
    "user": ["id", "email"],
    "org": ["id", "name"],
    "stt_usage": ["id", "detected_language"],
}


def _call(function: str, sql: str, dialect: str) -> Any:
    tokens = json.dumps(TOKENS[dialect][sql])
    return call(SQL_READ, f"c.{function}({tokens}, {json.dumps(SCHEMA)})")


def _problems(sql: str, dialect: str = "sqlite") -> list[tuple[str, str, str]]:
    found = _call("problems", sql, dialect)
    return [(p["severity"], p["message"], sql[p["from"] : p["to"]]) for p in found]


def test_a_table_the_schema_lacks() -> None:
    assert _problems("SELECT * FROM nope") == [("warning", "No table nope", "nope")]
    assert _problems("SELECT * FROM org o JOIN nope n ON n.id = o.id") == [
        ("warning", "No table nope", "nope")
    ]


def test_a_column_is_left_to_the_database() -> None:
    """Bare or through an alias: which table a name is from takes the
    database (a subquery may name an alias again)."""
    assert _problems("SELECT u.nope, email FROM user AS u") == []


def test_what_is_not_a_table_of_the_schemas_is_left_alone() -> None:
    """A WITH's name (with its columns, MATERIALIZED), a function read as a
    table, a subquery, a schema's table, the database's own catalog."""
    for sql in (
        "WITH t AS (SELECT 1) SELECT * FROM t",
        "WITH t (a) AS MATERIALIZED (SELECT 1) SELECT * FROM t",
        "SELECT * FROM generate_series(1, 3)",
        "SELECT * FROM (SELECT id FROM org) AS s",
        "SELECT * FROM main.anything",
        "SELECT * FROM sqlite_master",
    ):
        assert _problems(sql) == [], sql


def test_a_from_that_names_no_table_is_left_alone() -> None:
    """``EXTRACT(EPOCH FROM at)``, ``IS DISTINCT FROM``."""
    assert _problems("SELECT extract(EPOCH FROM at) FROM org", "postgresql") == []
    assert _problems("SELECT * FROM org WHERE id IS DISTINCT FROM name") == []


def test_a_grammar_error_and_an_open_quote_are_errors() -> None:
    assert [p[:2] for p in _problems("SELECT (1")] == [("error", "Syntax error")]
    assert _problems("SELECT 'abc") == [("error", "Unclosed quote", "'abc")]


def test_what_the_grammar_writes_its_own_way_is_not_wrong() -> None:
    """``u.*`` (the grammar's ``u.`` then ``*``), PostgreSQL's ``E'...'``."""
    assert _problems("SELECT u.* FROM user u") == []
    assert _problems("SELECT E'a\\nb'", "postgresql") == []


def _offered(sql: str) -> list[tuple[str, str]]:
    return [(o["label"], o["detail"]) for o in _call("columnsRead", sql, "sqlite")]


def test_the_columns_offered_are_the_tables_read() -> None:
    assert _offered("SELECT * FROM stt_usage WHERE detec") == [
        ("id", "stt_usage"),
        ("detected_language", "stt_usage"),
    ]
    assert _offered("SELECT * FROM user u JOIN org o ON o.id = u.id") == [
        ("id", "user"),
        ("email", "user"),
        ("id", "org"),
        ("name", "org"),
    ]
    assert _offered("SELECT * FROM nope") == []
