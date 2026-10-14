"""One read-only statement as Overseer runs it (``db_query``): writes fail
by construction (a read-only connection), never by reading the SQL; one
statement at a time; rows capped; a secret never shown; stopped past its
time; and the connection handed back as writable as it came."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self, cast

import pytest
from sqlalchemy import Connection, Engine, insert, select

from app.core import exposure
from app.core.config import settings
from app.services.system import db_query, db_rows
from tests.services._db_fixtures import META, ORG, seeded


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return seeded(tmp_path)


def _run(sql: str, engine: Engine) -> db_query.Answer:
    return db_query.run(sql, metadata=META, engine=engine)


def test_a_select_answers_with_its_rows(engine: Engine) -> None:
    found = _run("SELECT id, name FROM org ORDER BY id;", engine)
    assert found.columns == ["id", "name"]
    assert found.rows == [["3", "Acme"], ["5", "Initech"]]
    assert not found.more


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO org (id, name) VALUES (9, 'x')",
        "UPDATE org SET name = 'x'",
        "DELETE FROM org",
        "DROP TABLE org",
        "CREATE TABLE t (id INTEGER)",
        "WITH n AS (SELECT 9 AS id) INSERT INTO org (id, name) SELECT id, 'x' FROM n",
        "ATTACH DATABASE 'other.db' AS other",
        "PRAGMA query_only = OFF",
        "PRAGMA writable_schema = ON",
    ],
)
def test_a_write_fails(sql: str, engine: Engine) -> None:
    with pytest.raises(db_query.QueryError):
        _run(sql, engine)
    with engine.connect() as conn:
        assert len(conn.execute(select(ORG)).all()) == 2


def test_one_statement_at_a_time(engine: Engine) -> None:
    with pytest.raises(db_query.QueryError):
        _run("SELECT 1; SELECT 2", engine)
    with pytest.raises(db_query.QueryError):
        _run("  ;  ", engine)


def test_rows_are_capped_and_say_so(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_query, "LIMIT", 10)
    found = _run("SELECT id FROM member", engine)
    assert len(found.rows) == 10 and found.more


def test_a_secret_stays_hidden(engine: Engine) -> None:
    """Shown as hidden under its own name (``SELECT *``)."""
    found = _run("SELECT * FROM member", engine)
    assert {"hashed_password", "api_token"} <= found.masked
    at = found.columns.index("hashed_password")
    assert {row[at] for row in found.rows} == {db_rows.HIDDEN}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT hashed_password AS h FROM member",
        "SELECT 1, 2, 3, 4, 5, 6, 7, 8, 9 UNION ALL SELECT * FROM member",
        "WITH t(a, b, c, d, e, f, g, h, i) AS (SELECT * FROM member) SELECT * FROM t",
        "SELECT upper(hashed_password) FROM member",
    ],
)
def test_a_secret_renamed_is_never_read(sql: str, engine: Engine) -> None:
    """However the statement reaches it, the database reads it as empty."""
    found = _run(sql, engine)
    assert not any("$2b$" in cell.lower() for row in found.rows for cell in row)


def test_postgres_refuses_a_plan_reading_a_table_with_a_secret() -> None:
    """Postgres cannot blank a column, so a statement whose plan reads such
    a table (``EXPLAIN``) is refused; its rows are on Rows, masked."""
    plan = [
        {
            "Plan": {
                "Node Type": "Append",
                "Plans": [
                    {"Node Type": "Result"},
                    {"Node Type": "Seq Scan", "Relation Name": "member", "Alias": "m"},
                ],
            }
        }
    ]
    assert (
        db_query.secret_read(plan, {"member": frozenset({"hashed_password"})})
        == "member"
    )
    assert db_query.secret_read(plan, {"org": frozenset({"x"})}) is None


class _Postgres:
    """A Postgres connection's answers, in order (``is_superuser``, the
    plan, then the statement's: no rows), what it was sent, and whether it
    was thrown away."""

    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, *answers: Any) -> None:
        self.answers = iter(answers)
        self.sent: list[str] = []
        self.invalidated = False

    def exec_driver_sql(self, sql: str) -> SimpleNamespace:
        self.sent.append(sql)
        answer = next(self.answers, None)
        return SimpleNamespace(scalar=lambda: answer, returns_rows=False)

    def execution_options(self, **_: Any) -> Self:
        return self

    def invalidate(self) -> None:
        self.invalidated = True


def test_postgres_refuses_a_superuser_outside_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-only transaction does not stop a superuser's ``COPY ... TO
    PROGRAM``: outside dev, nothing is planned; in dev, it runs."""
    plan = [{"Plan": {"Node Type": "Result"}}]
    monkeypatch.setattr(settings, "APP_ENV", "production")
    conn = _Postgres("on")
    with pytest.raises(db_query.QueryError, match="superuser"):
        db_query._vet(cast(Connection, conn), "SELECT 1", {})
    assert len(conn.sent) == 1
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    db_query._vet(cast(Connection, _Postgres("on", plan)), "SELECT 1", {})


def test_postgres_throws_the_connection_away_after_each_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever a statement set (``SET``, a temp table) leaves with it,
    failed or not."""
    conn = _Postgres("off", [{"Plan": {"Node Type": "Result"}}])
    monkeypatch.setattr(db_rows, "reading", lambda *_: nullcontext(conn))
    with pytest.raises(db_query.QueryError, match="no rows"):
        db_query.run("SET work_mem = '1GB'", metadata=META)
    assert conn.invalidated and conn.sent[-1] == "SET work_mem = '1GB'"


def test_cells_are_redacted_and_cut(engine: Engine) -> None:
    bio, avatar = _run("SELECT bio, avatar FROM member WHERE id = 1", engine).rows[0]
    assert "s3cret" not in bio and len(bio) <= db_rows.CELL + 1
    assert avatar == "binary, 16 bytes"


def test_a_query_past_its_time_is_stopped(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """... and its connection still goes back writable."""
    monkeypatch.setattr(db_rows, "SECONDS", -1.0)
    monkeypatch.setattr(db_rows, "STEPS", 1)
    with pytest.raises(db_rows.ReadTooSlowError):
        _run(
            "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
            "SELECT count(*) FROM n",
            engine,
        )
    with engine.begin() as conn:
        conn.execute(insert(ORG), {"id": 9, "name": "Later"})


def test_the_connection_goes_back_writable(engine: Engine) -> None:
    """The pool hands the same connection to the app's next write."""
    with pytest.raises(db_query.QueryError):
        _run("DELETE FROM org", engine)
    _run("SELECT 1", engine)
    with engine.begin() as conn:
        conn.execute(insert(ORG), {"id": 9, "name": "Later"})


def test_hidden_where_rows_are_not_shown(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exposure, "refusal", lambda flag: "off here.")
    with pytest.raises(db_rows.RowsHiddenError):
        _run("SELECT 1", engine)


def test_secrets_are_read_from_every_table() -> None:
    found = db_rows.secrets(META)
    assert found == {"member": frozenset({"hashed_password", "api_token"})}
