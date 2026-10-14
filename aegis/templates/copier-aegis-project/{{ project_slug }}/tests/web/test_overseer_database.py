"""The Overseer Database page: the Flet database modal's tabs, Activity included."""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_container, overseer_database
from app.core import exposure
from app.core.config import settings
from app.services.system import db_query, db_rows, db_transactions
from app.services.system.models import ComponentStatus
from tests._audit import recording
from tests.web.dom import chosen, none, one, select, table_rows, text
from tests.web.overseer import sign_in, status_with

POSTGRES: dict[str, Any] = {
    "implementation": "postgresql",
    "version_short": "16.4",
    "url": "postgresql+asyncpg://app:s3cret@postgres:5432/app",
    "table_count": 2,
    "total_rows": 1234,
    "database_size_human": "8 MB",
    "active_connections": 3,
    "pg_settings": {"max_connections": 100, "work_mem": "4MB", "wal_level": "replica"},
    "connection_pool_size": 5,
    "total_indexes": 4,
    "total_foreign_keys": 1,
    "largest_table": {"name": "user", "rows": 1200},
    "table_schemas": [
        {
            "name": "user",
            "rows": 1200,
            "columns": [
                {
                    "name": "id",
                    "type": "INTEGER",
                    "nullable": False,
                    "primary_key": True,
                },
                {"name": "email", "type": "VARCHAR", "nullable": False},
            ],
            "indexes": [
                {"name": "ix_user_email", "columns": ["email"], "unique": True}
            ],
            "foreign_keys": [],
        },
    ],
    "migrations": [
        {
            "revision": "abcdef1234567890",
            "description": "create user",
            "is_current": True,
            "file_mtime": 0,
            "file_path": "alembic/versions/abcdef.py",
            "content": "def upgrade():\n\n    pass",
        },
    ],
}

SQLITE: dict[str, Any] = {
    "implementation": "sqlite",
    "version": "3.45.0",
    "url": "sqlite+aiosqlite:///./data/app.db",
    "file_size_human": "120 KB",
    "connection_pool_size": 1,
    "wal_enabled": True,
    "pragma_settings": {"journal_mode": "wal", "foreign_keys": True, "synchronous": 1},
    "comprehensive_pragma": {"page_size": 4096, "db_efficiency": 97.5},
    "activity": [
        {
            "kind": "locked",
            "seconds": None,
            "process": "worker:12",
            "caller": "app/services/ai/jobs.py:40 in score",
            "at": "2026-10-02T12:00:05+00:00",
        },
        {
            "kind": "slow",
            "seconds": 34.2,
            "process": "webserver:7",
            "caller": "app/services/ai/chat.py:88 in stream_turn",
            "at": "2026-10-02T12:00:00+00:00",
        },
    ],
}


def _client(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, Any]
) -> TestClient:
    database = ComponentStatus(name="database", message="Connected", metadata=metadata)
    sign_in(app, monkeypatch, status_with(database))
    return TestClient(app)


@pytest.fixture
def postgres(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    with _client(app, monkeypatch, POSTGRES) as client:
        yield client


@pytest.fixture
def sqlite(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    with _client(app, monkeypatch, SQLITE) as client:
        yield client


def _get(client: TestClient, tab: str = "") -> str:
    response = client.get("/overseer/components/database" + (f"/{tab}" if tab else ""))
    assert response.status_code == 200
    return response.text


def _figures(html: str) -> dict[str, str]:
    return {
        text(one(cell, "dt")): text(one(cell, "dd"))
        for cell in select(html, "#database-figures > div")
    }


class TestSections:
    def test_its_sections_with_overview_first(self, postgres: TestClient) -> None:
        """The engine's own parameters (Engine), then the runtime sections, then
        the app settings its code reads (Settings)."""
        html = _get(postgres)
        assert [text(a) for a in select(html, "#overseer-subnav nav a")] == [
            "Overview",
            "Schema",
            "Rows",
            "Query",
            "Migrations",
            "Engine",
            "Activity",
            "Transactions",
            "Container",
            "Logs",
            "Settings",
        ]
        assert text(one(html, "#overseer-subnav h2")) == "Database"
        assert "PostgreSQL 16.4" in text(one(html, "#overseer-subnav"))

    def test_unknown_section_is_404(self, postgres: TestClient) -> None:
        assert postgres.get("/overseer/components/database/nope").status_code == 404


class TestOverview:
    def test_postgres_figures(self, postgres: TestClient) -> None:
        figures = _figures(_get(postgres))
        assert figures["Total rows"] == "1,234"
        assert figures["Database size"] == "8 MB"
        assert figures["Connections"] == "3 / 100"

    def test_url_points_at_localhost_and_hides_the_password(
        self, postgres: TestClient
    ) -> None:
        url = text(one(_get(postgres), "#database-url code"))
        assert "@localhost:5432" in url
        assert "s3cret" not in url

    def test_sqlite_figures(self, sqlite: TestClient) -> None:
        figures = _figures(_get(sqlite))
        assert figures["Database size"] == "120 KB"
        assert figures["Connections"] == "1"


class TestSchema:
    def test_table_expands_to_create_statement(self, postgres: TestClient) -> None:
        html = _get(postgres, "schema")
        assert (
            text(one(html, "tbody tr:not([data-detail])").cssselect("td")[1]) == "user"
        )
        sql = text(one(html, "tr[data-detail] pre"))
        assert "email VARCHAR NOT NULL," in sql
        assert "PRIMARY KEY (id)" in sql
        assert "CREATE UNIQUE INDEX ix_user_email ON user (email);" in sql
        one(html, "tr[data-detail] .highlight")


ROWS = overseer_database.ROWS_URL


class TestRows:
    """A table's rows, read like Logs: one row of controls, then a flat
    scroller that takes the window, paged by the table's key. Read from the
    suite's own database (``SessionLocal``, every table created)."""

    def test_a_table_reads_like_the_logs(self, sqlite: TestClient) -> None:
        html = _get(sqlite, "rows")
        assert one(html, "[data-width]").get("data-width") == "workspace"
        picked = 'form[data-rows-controls] select[name="table"]'
        assert chosen(html, picked) == db_rows.tables()[0]
        assert one(html, "[data-scroll]") is not None
        assert select(html, "[data-rows] thead th")

    def test_a_secret_never_reaches_the_page(self, sqlite: TestClient) -> None:
        pytest.importorskip("app.models.user")  # the auth service's table
        first = table_rows(_get(sqlite, "rows?table=user"), "[data-rows]")[0]
        assert text(first["hashed_password"]) == db_rows.HIDDEN

    def test_the_next_page_follows_the_key(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("app.models.user")  # two seeded users to page
        monkeypatch.setattr(db_rows, "PAGE", 1)
        html = _get(sqlite, "rows?table=user")
        assert "after=" in (one(html, 'a[rel="next"]').get("href") or "")

    def test_a_row_opens_to_its_keys_and_each_refilters(
        self, sqlite: TestClient
    ) -> None:
        """No tab of its own: under each row, the rows it points at and
        that point at it, each a link that refilters the same scroller."""
        pytest.importorskip("app.models.user")
        user = db_rows.table_of("user")
        assert user is not None
        out, into = db_rows.keys(user)
        if not into:
            pytest.skip("nothing points at the user table in this stack")
        html = _get(sqlite, "rows?table=user")
        keys = text(one(html, "[data-keys]"))
        assert all(f"{k.table}.{k.columns[0]}" in keys for k in into)
        link = select(html, "#database-rows-body tr[data-links] a")[0]
        assert link.get("hx-target") == "#database-rows"
        href = link.get("href") or ""
        assert f"table={into[0].table}" in href and "where=" in href
        followed = sqlite.get(href)
        assert followed.status_code == 200
        one(followed.text, "[data-rows]")

    def test_an_unknown_table_is_not_found(self, sqlite: TestClient) -> None:
        assert sqlite.get(f"{ROWS}?table=nope").status_code == 404

    def test_off_outside_dev_until_it_is_turned_on(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rows are the app's data: outside dev, an admin turns them on."""
        monkeypatch.setattr(settings, "APP_ENV", "production")
        off = _get(sqlite, "rows")
        none(off, "[data-rows]")
        assert exposure.ROWS in text(one(off, "[data-rows-off]"))
        monkeypatch.setattr(settings, exposure.ROWS, True)
        one(_get(sqlite, "rows"), "[data-rows]")

    def test_schema_leads_to_each_readable_tables_rows(
        self, postgres: TestClient
    ) -> None:
        pytest.importorskip("app.models.user")
        html = _get(postgres, "schema")
        one(html, f'a[href="{ROWS}?table=user"]')


class TestQuery:
    """One read-only statement: a one-line prompt over the same flat
    scroller as Rows, its answer in it, every run audited."""

    def _run(self, client: TestClient, sql: str) -> str:
        response = client.post(overseer_database.QUERY_RUN, data={"sql": sql})
        assert response.status_code == 200
        return response.text

    def test_a_prompt_over_the_scroller(self, sqlite: TestClient) -> None:
        html = _get(sqlite, "query")
        assert one(html, "[data-width]").get("data-width") == "workspace"
        form = one(html, "form[data-query][data-write]")
        assert form.get("hx-post") == overseer_database.QUERY_RUN
        one(form, 'input[name="sql"]')
        one(html, "#database-query-answer [data-scroll]")

    def test_its_rows_and_what_it_cost(self, sqlite: TestClient) -> None:
        audit = recording(sqlite)
        html = self._run(sqlite, "SELECT 1 AS one, 'two' AS two")
        found = table_rows(html, "[data-rows]")
        assert [{k: text(v) for k, v in row.items()} for row in found] == [
            {"one": "1", "two": "two"}
        ]
        assert "read-only" in text(one(html, "[data-query-footer]"))
        assert [(e["event_type"], e["outcome"]) for e in audit.events] == [
            ("database.query", "ran")
        ]
        assert audit.events[0]["detail"] == "SELECT 1 AS one, 'two' AS two"

    def test_a_capped_answer_says_so(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(db_query, "LIMIT", 1)
        html = self._run(sqlite, "SELECT 1 UNION ALL SELECT 2")
        assert "first 1" in text(one(html, "[data-query-footer]"))

    def test_a_write_is_refused_and_audited(self, sqlite: TestClient) -> None:
        audit = recording(sqlite)
        html = self._run(sqlite, "DELETE FROM alembic_version")
        one(html, "[data-query-error]")
        none(html, "[data-rows]")
        assert audit.events[0]["outcome"] == "refused"

    def test_off_outside_dev_until_it_is_turned_on(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "APP_ENV", "production")
        off = _get(sqlite, "query")
        none(off, "form[data-query]")
        assert exposure.ROWS in text(one(off, "[data-rows-off]"))
        response = sqlite.post(overseer_database.QUERY_RUN, data={"sql": "SELECT 1"})
        assert response.status_code == 404


class TestMigrations:
    def test_marks_the_current_revision_and_shows_its_code(
        self, postgres: TestClient
    ) -> None:
        html = _get(postgres, "migrations")
        assert (
            text(one(html, "tbody tr:not([data-detail])").cssselect("td")[1])
            == "abcdef123456 (current)"
        )
        assert (
            "def upgrade():\n    pass"
            in one(html, "tr[data-detail] pre").text_content()
        )
        keywords = [text(k) for k in select(html, "tr[data-detail] .highlight span.k")]
        assert "def" in keywords


class TestSettings:
    def test_postgres_settings(self, postgres: TestClient) -> None:
        rows = {
            text(r.cssselect("td")[0]): text(r.cssselect("td")[1])
            for r in select(_get(postgres, "engine"), "tbody tr")
        }
        assert rows["max_connections"] == "100"
        assert rows["active_connections"] == "3"
        assert rows["wal_level"] == "replica"

    def test_sqlite_pragmas_read_as_words(self, sqlite: TestClient) -> None:
        rows = {
            text(r.cssselect("td")[0]): text(r.cssselect("td")[1])
            for r in select(_get(sqlite, "engine"), "tbody tr")
        }
        assert rows["journal_mode"] == "WAL"
        assert rows["synchronous"] == "NORMAL"
        assert rows["foreign_keys"] == "Enabled"
        assert rows["page_size"] == "4096 bytes"
        assert rows["db_efficiency"] == "97.50%"


class TestActivity:
    def test_slow_transactions_and_lock_waits_name_their_caller(
        self, sqlite: TestClient
    ) -> None:
        rows = [text(r) for r in select(_get(sqlite, "activity"), "tbody tr")]
        assert (
            "Locked" in rows[0] and "worker:12" in rows[0] and "jobs.py:40" in rows[0]
        )
        assert "34.2" in rows[1] and "chat.py:88 in stream_turn" in rows[1]

    def test_nothing_recorded_says_so(self, postgres: TestClient) -> None:
        assert "Nothing" in text(one(_get(postgres, "activity"), "#database-activity"))


def _row(**changes: Any) -> dict[str, Any]:
    return {
        "pid": None,
        "process": "worker:268",
        "code": "app/services/ai/jobs.py:44 in analyze_sentiment_job",
        "container": "app-worker-system-1",
        "state": "Holds the write lock",
        "seconds": 361.0,
        "wait": None,
        "blocked_by": [],
        "query": "",
        "trouble": True,
    } | changes


def _transactions(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], postgres: bool
) -> None:
    async def current() -> dict[str, Any]:
        return {"rows": rows, "postgres": postgres}

    monkeypatch.setattr(db_transactions, "current", current)


class TestTransactions:
    def test_sqlite_names_the_holder_marks_it_and_restarts_its_container(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SQLite cannot end another process's transaction: its container
        restarts, through the Restart every container row has."""
        quick = _row(process="webserver:7", container=None, seconds=1.5, trouble=False)
        _transactions(monkeypatch, [_row(), quick], postgres=False)
        held, short = select(
            _get(sqlite, "transactions"), "#database-transactions tbody tr"
        )
        assert "worker:268" in text(held) and "analyze_sentiment_job" in text(held)
        assert one(held, "[data-open-for] [data-tone]").get("data-tone") == "error"
        restart = one(held, "button")
        assert restart.get("hx-get") == overseer_container.RESTART.format(
            name="app-worker-system-1"
        )
        assert restart.get("data-write") is not None  # ``operator_refusal``
        assert not select(short, "button")
        assert one(short, "[data-open-for] [data-tone]").get("data-tone") != "error"

    def test_postgres_shows_every_connection_and_ends_one(
        self, postgres: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = [
            _row(pid=41, code="", container=None, state="idle in transaction"),
            _row(
                pid=42,
                code="",
                container=None,
                state="active",
                seconds=0.5,
                trouble=False,
                blocked_by=[41],
                wait="Lock: transactionid",
                query="UPDATE llm_model SET name = $1",
            ),
        ]
        _transactions(monkeypatch, rows, postgres=True)
        html = _get(postgres, "transactions")
        holder, waiter = select(html, "#database-transactions tbody tr")
        end = one(holder, "button")
        assert end.get("hx-get") == overseer_database.END_CONFIRM.format(pid=41)
        assert end.get("data-write") is not None  # ``operator_refusal``
        assert "41" in text(one(waiter, "[data-blocked-by]"))
        assert "UPDATE llm_model" in text(waiter)
        assert "2 connections" in text(one(html, "#database-transactions"))

    def test_nothing_held_says_so(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _transactions(monkeypatch, [], postgres=False)
        assert "Nothing" in text(
            one(_get(sqlite, "transactions"), "#database-transactions")
        )

    async def test_the_stream_sends_the_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _transactions(monkeypatch, [_row()], postgres=False)
        frames = [f async for f in overseer_database.events(max_frames=1)]
        assert frames[0].startswith(f"event: {overseer_database.EVENT}")
        assert "worker:268" in frames[0]

    def test_ending_a_connection_confirms_first(self, postgres: TestClient) -> None:
        dialog = postgres.get(overseer_database.END_CONFIRM.format(pid=41)).text
        form = one(dialog, "[hx-post]")
        assert form.get("hx-post") == overseer_database.END_API.format(pid=41)
