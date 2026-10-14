"""The Overseer Database page: the Flet database modal's tabs, Activity included."""

from collections.abc import Generator
import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import (
    overseer_container,
    overseer_database,
    overseer_database_browser,
)
from app.core import exposure
from app.core.config import settings
from app.services.system import db_filters, db_query, db_rows, db_transactions
from app.services.system.models import ComponentStatus
from tests._audit import recording
from tests.web.dom import none, one, select, table_rows, text
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
            "Tables",
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


TABLES = overseer_database_browser.TABLES_URL
QUERY = overseer_database_browser.QUERY_URL


def _tab(client: TestClient, table: str, tab: str = "") -> str:
    query = f"?table={table}" + (f"&tab={tab}" if tab else "")
    response = client.get(TABLES + query)
    assert response.status_code == 200
    return response.text


class TestTables:
    """Everything about a table in one place, the whole width its own: the
    table's Rows, Schema and Relationships as tabs, and beside them the
    table picked, opening to the schema's tables to pick another."""

    def test_the_picker_opens_to_the_tables_under_their_schema(
        self, postgres: TestClient
    ) -> None:
        html = _get(postgres, "tables")
        assert one(html, "[data-width]").get("data-width") == "workspace"
        picker = one(html, "#database-table [data-tables-picker] details")
        assert text(one(picker, "summary")) == "user"
        assert "public" in text(one(picker, "[data-schema]"))
        listed = one(picker, "[data-tables-list]")
        search = one(picker, "input[data-filter]")  # app.js, no request
        assert listed.get("id") and search.get("data-filter") == f"#{listed.get('id')}"
        link = one(listed, f'a[href="{TABLES}?table=user"]')
        assert link.get("hx-target") == "#database-table"
        assert "1,200" in text(link)

    def test_a_table_opens_on_its_tabs(self, postgres: TestClient) -> None:
        pytest.importorskip("app.models.user")
        html = _tab(postgres, "user")
        tabs = select(
            html, "#database-table [role=tablist] > a:not([data-query-table])"
        )
        assert [text(a) for a in tabs] == ["Rows", "Schema", "Relationships"]
        assert tabs[0].get("aria-current") == "page"
        query = one(html, "#database-table a[data-query-table]")
        assert query.get("href") == f"{QUERY}?table=user"
        assert tabs[1].get("href") == f"{TABLES}?table=user&tab=schema"
        assert tabs[1].get("hx-target") == "#database-table"

    def test_its_schema_is_its_create_statement(self, postgres: TestClient) -> None:
        sql = text(one(_tab(postgres, "user", "schema"), "#database-table pre"))
        assert "email VARCHAR NOT NULL," in sql
        assert "PRIMARY KEY (id)" in sql
        assert "CREATE UNIQUE INDEX ix_user_email ON user (email);" in sql

    def test_its_relationships_are_drawn_as_the_map_draws(
        self, sqlite: TestClient
    ) -> None:
        """The map's own nodes and lines (overseer_map, across): the tables
        pointing at it on the left, it in the middle, each a node with its
        keys on hover, leading to that table's relationships."""
        pytest.importorskip("app.models.user")
        user = db_rows.table_of("user")
        assert user is not None
        _, into = db_rows.keys(user)
        if not into:
            pytest.skip("nothing points at the user table in this stack")
        html = _tab(sqlite, "user", "relationships")
        one(html, "#database-table [data-map][data-across]")
        one(html, '[data-node="user"]')
        other = one(html, f'[data-node="{into[0].table}"]')
        assert f"{into[0].table}.{into[0].columns[0]}" in text(
            one(other, "[data-hint]")
        )
        title = one(other, "a[data-title]")
        assert title.get("href") == f"{TABLES}?table={into[0].table}&tab=relationships"
        assert title.get("hx-target") == "#database-table"  # as its tabs do
        one(html, f'path[data-link][data-from="{into[0].table}"][data-to="user"]')

    def test_a_table_the_models_do_not_declare_opens_on_its_schema(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its rows are not read (``db_rows`` reads the models' tables)."""
        legacy = {"name": "legacy", "rows": 3, "columns": [{"name": "id"}]}
        metadata = POSTGRES | {"table_schemas": [legacy]}
        with _client(app, monkeypatch, metadata) as client:
            html = _tab(client, "legacy")
            assert "CREATE TABLE IF NOT EXISTS legacy" in text(one(html, "pre"))
            one(_tab(client, "legacy", "rows"), "[data-unread]")

    def test_an_unknown_table_is_not_found(self, sqlite: TestClient) -> None:
        assert sqlite.get(f"{TABLES}?table=nope").status_code == 404


class TestRows:
    """A table's Rows tab, read like Logs: one row of controls, then a flat
    scroller that takes the rest of the pane, paged by the table's key.
    Read from the suite's own database (``SessionLocal``, every table
    created)."""

    def test_a_table_reads_like_the_logs(self, sqlite: TestClient) -> None:
        html = _get(sqlite, "tables")
        assert one(html, "#database-rows [data-scroll]") is not None
        assert select(html, "[data-rows] thead th")

    def test_a_secret_never_reaches_the_page(self, sqlite: TestClient) -> None:
        pytest.importorskip("app.models.user")  # the auth service's table
        first = table_rows(_tab(sqlite, "user"), "[data-rows]")[0]
        assert text(first["hashed_password"]) == db_rows.HIDDEN

    def test_the_next_page_follows_the_key(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("app.models.user")  # two seeded users to page
        monkeypatch.setattr(db_rows, "PAGE", 1)
        html = _tab(sqlite, "user")
        assert "after=" in (one(html, 'a[rel="next"]').get("href") or "")

    def test_a_row_opens_to_its_keys_and_each_opens_that_table(
        self, sqlite: TestClient
    ) -> None:
        """Under each row, the rows it points at and that point at it, each
        a link opening the other table's rows, filtered to them."""
        pytest.importorskip("app.models.user")
        user = db_rows.table_of("user")
        assert user is not None
        _, into = db_rows.keys(user)
        if not into:
            pytest.skip("nothing points at the user table in this stack")
        html = _tab(sqlite, "user")
        # across the whole row (a flex cell would sit in the first column)
        link = select(html, "#database-rows-body tr[data-links] > td[colspan] > div a")[
            0
        ]
        assert link.get("hx-target") == "#database-table"
        href = link.get("href") or ""
        assert f"table={into[0].table}" in href and "where=" in href
        followed = sqlite.get(href)
        assert followed.status_code == 200
        one(followed.text, "[data-rows]")

    def test_a_header_orders_the_table_or_sorts_the_page(
        self, sqlite: TestClient
    ) -> None:
        """A column an index serves orders the whole table (the server, by
        key, again for the other way); any other sorts the rows shown."""
        pytest.importorskip("app.models.user")
        user = db_rows.table_of("user")
        assert user is not None
        html = _tab(sqlite, "user")
        key = one(html, 'th[data-column="id"]')
        assert key.get("aria-sort") == "ascending"
        link = one(key, "a")
        assert link.get("hx-target") == "#database-rows"
        assert "order=id" in (link.get("href") or "")
        assert "dir=desc" in (link.get("href") or "")
        other = next(c for c in user.columns.keys() if c not in db_rows.sortable(user))
        one(html, f'th[data-column="{other}"] button[data-sort-rows]')

    def test_a_filter_is_a_column_picked_and_a_value(self, sqlite: TestClient) -> None:
        """A column the table has (never a secret), how it compares, a value,
        each filter a chip that takes it away; one the URL names that it
        does not have says so in place of the rows."""
        pytest.importorskip("app.models.user")
        user = db_rows.table_of("user")
        assert user is not None
        html = _tab(sqlite, "user")
        picks = [
            o.get("value")
            for o in select(
                html, 'form[data-rows-controls] select[name="column"] option'
            )
        ]
        assert picks == db_rows.filterable(user)
        controls = one(html, "form[data-rows-controls] [data-filter-allowed]")
        allowed = json.loads(controls.get("data-filter-allowed") or "")
        assert allowed["id"] == list(db_filters.OPERATORS)  # in the page, no request
        assert allowed["email"] == [":", "!="]
        ops = [o.get("value") for o in select(html, 'select[name="op"] option')]
        assert ops == [":", "!=", "<", "<=", ">", ">="]
        found = sqlite.get(f"{TABLES}?table=user&column=id&op=%3A&value=1").text
        at = list(user.columns.keys()).index("id")
        ids = {
            text(r.cssselect("td")[at])
            for r in select(found, "#database-rows-body tr.log-row")
        }
        assert ids == {"1"}
        chip = one(found, "[data-filter-chip]")
        assert "id" in text(chip) and "where" not in (chip.get("href") or "")
        later = sqlite.get(f"{TABLES}?table=user&column=id&op=%3E%3D&value=2").text
        assert "id ≥ 2" in text(one(later, "[data-filter-chip]"))
        comma = sqlite.get(f"{TABLES}?table=user&column=email&op=%3A&value=a,b").text
        one(comma, "[data-rows-bad]")
        none(comma, "[data-filter-chip]")  # the filter it could not carry, gone
        bad = sqlite.get(f"{TABLES}?table=user&where=nope:1")
        assert bad.status_code == 200
        assert "nope" in text(one(bad.text, "[data-rows-bad]"))
        one(bad.text, 'form[data-rows-controls] select[name="column"]')

    def test_every_link_keeps_the_rest_of_what_was_asked(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Clicking around a filtered, ordered table resets nothing: a chip
        keeps the order and the other filter, a header the filters, the next
        page all of it; a column no index serves says it reads the table."""
        pytest.importorskip("app.models.user")
        monkeypatch.setattr(db_rows, "PAGE", 1)
        html = _tab(sqlite, "user&order=email&dir=desc&where=id>=1,id<=99")
        chip = select(html, "[data-filter-chip]")[0].get("href") or ""
        assert "order=email" in chip and "dir=desc" in chip and "id%3C%3D99" in chip
        email = one(html, 'th[data-column="email"] a').get("href") or ""
        assert "where=" in email and "dir=" not in email  # the other way now
        assert "where=" in (one(html, 'th[data-column="id"] a').get("href") or "")
        later = one(html, 'a[rel="next"]').get("href") or ""
        assert all(part in later for part in ("where=", "order=email", "page=2"))
        labels = {
            o.get("value"): text(o)
            for o in select(html, 'select[name="column"] option')
        }
        assert labels["id"] == "id" and "(no index)" in labels["full_name"]

    def test_a_swap_of_the_rows_alone_leaves_out_the_picker(
        self, sqlite: TestClient
    ) -> None:
        """Paging, sorting and filtering swap the rows; the picker's every
        table would be rendered and thrown away."""
        name = db_rows.tables()[0]
        url = f"{TABLES}?table={name}"
        swap = sqlite.get(
            url, headers={"HX-Request": "true", "HX-Target": "database-rows"}
        )
        one(swap.text, "#database-rows [data-rows]")
        none(swap.text, "[data-tables-list] a")
        assert select(_tab(sqlite, name), "[data-tables-list] a")

    def test_a_read_past_its_time_says_so(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def slow(*_: object, **__: object) -> None:
            raise db_rows.ReadTooSlowError("Stopped after 5 seconds.")

        monkeypatch.setattr(db_rows, "page", slow)
        html = _tab(sqlite, db_rows.tables()[0])
        assert "Stopped" in text(one(html, "[data-rows-slow]"))

    def test_every_read_is_audited(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rows are the app's data: who read which table, how it was
        asked, and how it went (ran, refused, stopped); a tab that reads
        none is not recorded."""

        def slow(*_: object, **__: object) -> None:
            raise db_rows.ReadTooSlowError("Stopped after 5 seconds.")

        name = db_rows.tables()[0]
        audit = recording(sqlite)
        _tab(sqlite, name)
        _tab(sqlite, name, "schema")
        assert sqlite.get(f"{TABLES}?table={name}&where=nope:1").status_code == 200
        monkeypatch.setattr(db_rows, "page", slow)
        _tab(sqlite, name)
        assert [(e["event_type"], e["outcome"], e["table"]) for e in audit.events] == [
            ("database.rows", "ran", name),
            ("database.rows", "refused", name),
            ("database.rows", "stopped", name),
        ]
        assert audit.events[1]["where"] == "nope:1"

    def test_the_rows_shown_download_or_copy(self, sqlite: TestClient) -> None:
        html = _tab(sqlite, db_rows.tables()[0])
        formats = select(html, '[data-export-rows="#database-rows-body"]')
        assert [(f.get("data-export-to"), f.get("data-export")) for f in formats] == [
            ("file", "csv"),
            ("file", "json"),
            ("copy", "tsv"),
            ("copy", "csv"),
            ("copy", "json"),
            ("copy", "markdown"),
        ]

    def test_off_outside_dev_until_it_is_turned_on(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rows are the app's data: outside dev, an admin turns them on;
        the table opens on its schema meanwhile."""
        monkeypatch.setattr(settings, "APP_ENV", "production")
        name = db_rows.tables()[0]
        none(_tab(sqlite, name), "[data-rows]")
        off = _tab(sqlite, name, "rows")
        none(off, "[data-rows]")
        assert exposure.ROWS in text(one(off, "[data-rows-off]"))
        monkeypatch.setattr(settings, exposure.ROWS, True)
        one(_tab(sqlite, name), "[data-rows]")


class TestQuery:
    """One read-only statement at a time, written in an editor that takes
    the top of the window (sql.js keeps its tabs), its answer in the same
    flat scroller as Rows under it, every run audited."""

    def _run(self, client: TestClient, sql: str) -> str:
        response = client.post(overseer_database_browser.QUERY_RUN, data={"sql": sql})
        assert response.status_code == 200
        return response.text

    def test_an_editor_over_the_scroller(self, sqlite: TestClient) -> None:
        html = _get(sqlite, "query")
        assert one(html, "[data-width]").get("data-width") == "workspace"
        one(html, "#database-query[data-sql-workbench] [data-sql-tabs]")
        form = one(html, "form[data-query][data-write]")
        assert form.get("hx-post") == overseer_database_browser.QUERY_RUN
        one(form, 'textarea[name="sql"]')  # without the script, still a prompt
        one(
            html,
            '[data-export-to="file"][data-export="csv"][data-export-rows="#database-query-body"]',
        )
        one(html, "#database-query-answer [data-scroll]")

    def test_a_table_opens_a_tab_reading_it(self, postgres: TestClient) -> None:
        """From Tables: a new tab with the table's rows, named as the
        dialect needs (``user`` is a word of PostgreSQL's)."""
        html = _get(postgres, "query?table=user")
        seed = one(html, "[data-sql-workbench]").get("data-seed")
        assert seed == 'SELECT * FROM "user"'
        assert one(_get(postgres, "query?table=nope"), "[data-sql-workbench]").get(
            "data-seed"
        ) in (None, "")

    def test_the_prompt_knows_the_dialect_and_each_tables_columns(
        self, postgres: TestClient
    ) -> None:
        """For the editor (sql.js): highlighting in the database's dialect,
        completing its tables and their columns."""
        editor = one(_get(postgres, "query"), "[data-sql-editor]")
        assert editor.get("data-dialect") == "postgresql"
        assert json.loads(editor.get("data-schema") or "") == {"user": ["id", "email"]}

    def test_its_rows_and_what_it_cost(self, sqlite: TestClient) -> None:
        audit = recording(sqlite)
        html = self._run(sqlite, "SELECT 1 AS one, 'two' AS two")
        found = table_rows(html, "[data-rows]")
        assert [{k: text(v) for k, v in row.items()} for row in found] == [
            {"one": "1", "two": "two"}
        ]
        assert "read-only" in text(one(html, "[data-query-footer]"))
        assert len(select(html, "th button[data-sort-rows]")) == 2
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

    def test_a_statement_past_its_time_is_audited_as_stopped(
        self, sqlite: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def slow(*_: object, **__: object) -> None:
            raise db_rows.ReadTooSlowError("Stopped after 5 seconds.")

        monkeypatch.setattr(db_query, "run", slow)
        audit = recording(sqlite)
        html = self._run(sqlite, "SELECT 1")
        assert "Stopped" in text(one(html, "[data-query-error]"))
        assert audit.events[0]["outcome"] == "stopped"

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
        response = sqlite.post(
            overseer_database_browser.QUERY_RUN, data={"sql": "SELECT 1"}
        )
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
