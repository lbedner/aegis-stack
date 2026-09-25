"""An index on a column is not a foreign key on it.

``_additive`` drops a constraint the database already has under another
name, and decided "already has" by column set alone - indexes, unique
constraints and foreign keys pooled together. Every finance
``owner_user_id`` carries an index, so the foreign key auth adds on that
same column read as present and was dropped: adding auth to an existing
finance project left all of its owner columns without a key (#1217).
"""

from __future__ import annotations

import os
from typing import Any

import sqlalchemy as sa
from alembic.operations import ops
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _generator() -> dict[str, Any]:
    """``migrate_gen``'s constraint logic, rendered and run in isolation."""
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    source = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/app/cli/migrate_gen.py.jinja"
    ).render({**get_copier_defaults(), "include_database": True})
    start = source.index("def _reflected_column_sets(")
    end = source.index("def _qualified(")
    namespace: dict[str, Any] = {
        "Any": Any,
        "inspect": sa.inspect,
        "text": sa.text,
        "TextClause": sa.TextClause,
        "Connection": sa.Connection,
        "os": os,
        "ops": ops,
    }
    exec(source[start:end], namespace)  # noqa: S102
    return namespace


def _conn_with_indexed_owner() -> sa.Connection:
    engine = sa.create_engine("sqlite://")
    conn = engine.connect()
    conn.execute(sa.text("CREATE TABLE user (id INTEGER PRIMARY KEY)"))
    conn.execute(
        sa.text("CREATE TABLE ledger (id INTEGER PRIMARY KEY, owner_user_id INTEGER)")
    )
    conn.execute(sa.text("CREATE INDEX ix_ledger_owner ON ledger (owner_user_id)"))
    return conn


def _owner_fk() -> ops.CreateForeignKeyOp:
    return ops.CreateForeignKeyOp(
        "fk_ledger_owner_user_id_user",
        "ledger",
        "user",
        ["owner_user_id"],
        ["id"],
    )


def test_a_foreign_key_is_kept_when_only_an_index_covers_its_column() -> None:
    gen = _generator()
    conn = _conn_with_indexed_owner()

    assert gen["_additive"](_owner_fk(), conn) is True


def test_a_foreign_key_the_database_already_has_is_still_dropped() -> None:
    """The dedup the check exists for still holds - for the same KIND."""
    gen = _generator()
    engine = sa.create_engine("sqlite://")
    conn = engine.connect()
    conn.execute(sa.text("CREATE TABLE user (id INTEGER PRIMARY KEY)"))
    conn.execute(
        sa.text(
            "CREATE TABLE ledger (id INTEGER PRIMARY KEY,"
            " owner_user_id INTEGER REFERENCES user (id))"
        )
    )

    assert gen["_additive"](_owner_fk(), conn) is False


def test_an_index_the_database_already_has_is_still_dropped() -> None:
    gen = _generator()
    conn = _conn_with_indexed_owner()
    op = ops.CreateIndexOp("ix_ledger_owner_again", "ledger", ["owner_user_id"])

    assert gen["_additive"](op, conn) is False
