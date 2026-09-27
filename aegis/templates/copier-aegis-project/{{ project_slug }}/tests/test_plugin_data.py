"""A removed plugin's rows survive its removal and come back when it does.

``aegis remove <plugin>`` writes a revision that exports each of the
plugin's tables and then drops it; re-adding the plugin writes a revision
that recreates them and restores the latest export. These are the two calls
those revisions make.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="no database in this stack")

from sqlalchemy import (  # noqa: E402
    Column,
    Connection,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    select,
)

from app.cli import plugin_data  # noqa: E402

WHEN = datetime(2026, 9, 26, 12, 30, tzinfo=UTC).replace(tzinfo=None)


def _page_table(metadata: MetaData, *, with_title: bool = True) -> Table:
    columns = [
        Column("id", Integer, primary_key=True),
        Column("url", String(200), unique=True, nullable=False),
        Column("fetched_at", DateTime),
        Column("score", Numeric(10, 2)),
        Column("body", LargeBinary),
    ]
    if with_title:
        columns.append(Column("title", String(100)))
    return Table("crawled_page", metadata, *columns)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(plugin_data.settings, "STORAGE_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def conn() -> Iterator[Connection]:
    with create_engine("sqlite://").connect() as connection:
        yield connection


def _seed(conn: Connection) -> None:
    table = _page_table(metadata := MetaData())
    metadata.create_all(conn)
    conn.execute(
        table.insert(),
        [
            {
                "url": "https://a.test",
                "fetched_at": WHEN,
                "score": Decimal("9.50"),
                "body": b"\x00\xffraw",
                "title": "A",
            },
            {
                "url": "https://b.test",
                "fetched_at": None,
                "score": None,
                "body": None,
                "title": None,
            },
        ],
    )


def _recreate(conn: Connection, *, with_title: bool = True) -> Table:
    conn.exec_driver_sql("DROP TABLE crawled_page")
    table = _page_table(metadata := MetaData(), with_title=with_title)
    metadata.create_all(conn)
    return table


def test_export_then_restore_brings_every_row_back(store: Path, conn: Connection) -> None:
    _seed(conn)
    before = conn.execute(select(_page_table(MetaData()))).all()

    assert plugin_data.export_table(conn, "crawled_page") == 2
    _recreate(conn)
    assert plugin_data.restore_table(conn, "crawled_page") == 2

    assert conn.execute(select(_page_table(MetaData()))).all() == before


def test_a_column_the_table_no_longer_has_is_left_out(
    store: Path, conn: Connection
) -> None:
    """A plugin upgrade between remove and re-add may drop a column."""
    _seed(conn)
    plugin_data.export_table(conn, "crawled_page")
    table = _recreate(conn, with_title=False)

    assert plugin_data.restore_table(conn, "crawled_page") == 2
    assert conn.execute(select(table.c.url)).scalars().all() == [
        "https://a.test",
        "https://b.test",
    ]


def test_a_row_the_table_refuses_is_skipped_not_fatal(
    store: Path, conn: Connection
) -> None:
    _seed(conn)
    plugin_data.export_table(conn, "crawled_page")
    table = _recreate(conn)
    conn.execute(table.insert().values(url="https://a.test"))

    assert plugin_data.restore_table(conn, "crawled_page") == 1


def test_nothing_exported_restores_nothing(store: Path, conn: Connection) -> None:
    _page_table(metadata := MetaData())
    metadata.create_all(conn)

    assert plugin_data.restore_table(conn, "crawled_page") == 0


def test_the_latest_export_wins(store: Path, conn: Connection) -> None:
    _seed(conn)
    plugin_data.export_table(conn, "crawled_page")
    page = _page_table(MetaData())
    conn.execute(page.delete().where(page.c.id == 2))
    plugin_data.export_table(conn, "crawled_page")
    _recreate(conn)

    assert plugin_data.restore_table(conn, "crawled_page") == 1


def test_a_scratch_replay_neither_exports_nor_restores(
    store: Path, conn: Connection
) -> None:
    """migrate_gen and the drift check replay every revision onto a scratch
    database; an export there would write an empty file that a later
    restore would take for the latest."""
    _seed(conn)
    conn.info[plugin_data.SCRATCH] = True

    assert plugin_data.export_table(conn, "crawled_page") == 0
    assert not list(store.rglob("*.jsonl"))


def test_an_orphan_is_a_table_no_model_describes(conn: Connection) -> None:
    """What ``migrate_drop`` retires is exactly what the drift check calls
    ``remove_table``: a table in the database that no model describes."""
    pytest.importorskip("alembic", reason="no migrations in this stack")
    from app.cli.migrate_drop import orphaned_tables

    Table("left_behind", metadata := MetaData(), Column("id", Integer, primary_key=True))
    metadata.create_all(conn)

    assert [t.name for t in orphaned_tables(conn)] == ["left_behind"]
