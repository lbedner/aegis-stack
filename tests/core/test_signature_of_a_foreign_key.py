"""The signature of a revision whose diff adds a foreign key.

``migrate_gen`` records, for each generated revision, the object that
proves it ran - a table, a column, or a foreign key. Startup uses that
signature to STAMP a database that already has the object instead of
replaying the DDL, so a revision whose signature cannot be computed
takes the whole adoption walk down with it.

The foreign-key branch read ``op.source_schema``. Alembic's
``CreateForeignKeyOp`` signature is ``(constraint_name, source_table,
referent_table, local_cols, remote_cols, **kw)`` - the schema goes into
``kw`` and there is no such attribute. So the branch raised
``AttributeError`` for every diff containing a foreign key, and the
revision was never written.

Found adding the auth service to a real project on 2026-09-20 (alembic
1.16.5). Not version skew: the same alembic is pinned on both sides.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic.operations import ops
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _signature_fn() -> Any:
    """``_signature`` out of the rendered template, with its helper."""
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    source = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/app/cli/migrate_gen.py.jinja"
    ).render({**get_copier_defaults(), "include_database": True})
    start = source.index("def _qualified(")
    end = source.index("def _prune(")
    namespace: dict[str, Any] = {"Any": Any, "ops": ops, "text": sa.text}
    exec(source[start:end], namespace)  # noqa: S102
    return namespace["_signature"]


def test_alembic_really_has_no_source_schema_attribute() -> None:
    """Pins the assumption the fix rests on, so a future alembic that
    adds the attribute does not leave the workaround looking arbitrary."""
    op = ops.CreateForeignKeyOp(
        "fk_child_parent", "child", "parent", ["parent_id"], ["id"]
    )
    assert not hasattr(op, "source_schema")
    assert hasattr(op, "kw")


def test_a_foreign_key_gets_a_signature_instead_of_an_attribute_error() -> None:
    signature = _signature_fn()(
        [
            ops.CreateForeignKeyOp(
                "fk_child_parent", "child", "parent", ["parent_id"], ["id"]
            )
        ]
    )
    assert signature == ("foreign_key", "child", "parent_id")


def test_the_schema_comes_from_kw_when_there_is_one() -> None:
    signature = _signature_fn()(
        [
            ops.CreateForeignKeyOp(
                "fk_child_parent",
                "child",
                "parent",
                ["parent_id"],
                ["id"],
                source_schema="finance",
            )
        ]
    )
    assert signature == ("foreign_key", "finance.child", "parent_id")
