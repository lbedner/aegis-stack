"""Memory modules are context modules: the rename keeps every row.

The table and the agent column are renamed by the models, and a revision
derived from models only adds (``migrate_gen``): it creates
``context_module`` and ``agent.context_modules`` beside the old ones. The
agents revision carries the rows over, ids included, and each agent's list
of modules, then retires the old names.
"""

from __future__ import annotations

import sqlalchemy as sa

from aegis.core.migration_generator import AGENTS_MIGRATION
from tests.core._data_after import run_data_after

_MODULE_COLUMNS = (
    "id INTEGER PRIMARY KEY, slug VARCHAR NOT NULL, name VARCHAR NOT NULL, "
    "description VARCHAR, category VARCHAR, prompt_content VARCHAR, "
    "fetch_function VARCHAR, context_key VARCHAR NOT NULL, "
    "supports_days_back BOOLEAN NOT NULL, default_days_back INTEGER, "
    "priority INTEGER NOT NULL, token_estimate INTEGER NOT NULL, "
    "is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL, "
    "updated_at DATETIME NOT NULL"
)


def _upgrade(conn: sa.Connection) -> None:
    run_data_after(conn, AGENTS_MIGRATION.data_after)


def _renamed(conn: sa.Connection, *, old: bool) -> None:
    """The tables as the agents revision leaves them, before its data: the
    new names created (with what context modules have since gained, by its
    server default), the old ones still there when ``old``."""
    conn.exec_driver_sql(
        f"CREATE TABLE context_module ({_MODULE_COLUMNS}, "
        "per_subject BOOLEAN NOT NULL DEFAULT 0)"
    )
    extra = ", memory_modules JSON NOT NULL DEFAULT '[]'" if old else ""
    conn.exec_driver_sql(
        "CREATE TABLE agent (id INTEGER PRIMARY KEY, slug VARCHAR NOT NULL, "
        f"context_modules JSON NOT NULL DEFAULT '[]'{extra})"
    )
    if old:
        conn.exec_driver_sql(f"CREATE TABLE memory_module ({_MODULE_COLUMNS})")


def test_modules_move_with_their_ids_and_agents_keep_their_lists() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _renamed(conn, old=True)
        conn.exec_driver_sql(
            "INSERT INTO memory_module (id, slug, name, context_key,"
            " supports_days_back, priority, token_estimate, is_active,"
            " created_at, updated_at) VALUES (4, 'app_map', 'App map', 'map',"
            " 0, 10, 0, 1, '2026-11-01', '2026-11-01')"
        )
        conn.exec_driver_sql(
            "INSERT INTO agent (id, slug, memory_modules)"
            " VALUES (1, 'assistant', '[\"app_map\"]')"
        )

        _upgrade(conn)

        assert conn.exec_driver_sql("SELECT id, slug FROM context_module").all() == [
            (4, "app_map")
        ]
        assert conn.exec_driver_sql("SELECT context_modules FROM agent").scalar() == (
            '["app_map"]'
        )
        inspector = sa.inspect(conn)
        assert not inspector.has_table("memory_module")
        assert "memory_modules" not in {
            c["name"] for c in inspector.get_columns("agent")
        }


def test_a_project_born_after_the_rename_is_untouched() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        _renamed(conn, old=False)

        _upgrade(conn)

        assert conn.exec_driver_sql("SELECT COUNT(*) FROM context_module").scalar() == 0
