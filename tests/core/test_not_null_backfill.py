"""A column added to a table that already has rows needs a value for them.

The generator derives revisions by diffing the models against a scratch
database that is empty by construction, and every database the revision
then runs on is not. These are the fast checks for that gap; the end-to-end
proof is the published-release pair in the upgrade matrix, which is slow
and needs the network, so it never runs on a pull request.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from alembic.operations import ops
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path
from aegis.core.migration_generator import _prepend_to_upgrade

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"


def _generator_module() -> Any:
    """The project's ``migrate_gen``, rendered and executed in isolation.

    Rendered rather than imported: the file ships as a template, and the
    logic under test only exists once Jinja has run.
    """
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    source = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/app/cli/migrate_gen.py.jinja"
    ).render({**get_copier_defaults(), "include_database": True})
    # The module imports the project's own registry at import time, which
    # does not exist here, so only the pure functions are taken: everything
    # under test operates on alembic ops and needs no project.
    start = source.index("CLEARED_TABLES")
    end = source.index("def _additive(")
    namespace: dict[str, Any] = {
        "Any": Any,
        "text": sa.text,
        "os": __import__("os"),
        "ops": ops,
    }
    exec(source[start:end], namespace)  # noqa: S102
    exec(_additive_source(source), namespace)  # noqa: S102
    return namespace


def _additive_source(source: str) -> str:
    start = source.index("def _additive(")
    end = source.index("def _qualified(")
    return source[start:end]


def _add_column(
    column: sa.Column[Any], table: str = "llm_deployment"
) -> ops.AddColumnOp:
    return ops.AddColumnOp(table, column)


class TestBackfillingAnAddedColumn:
    """``_backfill_not_null``: what the rows that predate the column get."""

    def test_the_models_default_becomes_a_server_default(self) -> None:
        gen = _generator_module()
        column = sa.Column("enabled", sa.Boolean(), nullable=False, default=True)

        gen["_backfill_not_null"](_add_column(column))

        # Without this the column arrives NOT NULL with nothing to fill it:
        # SQLModel's default is Python-side and the database never sees it.
        assert column.server_default is not None

    def test_a_string_default_is_quoted_and_escaped(self) -> None:
        gen = _generator_module()
        column = sa.Column("label", sa.String(), nullable=False, default="it's")

        gen["_backfill_not_null"](_add_column(column))

        assert str(column.server_default) == "'it''s'"

    def test_a_nullable_column_is_left_alone(self) -> None:
        gen = _generator_module()
        column = sa.Column("note", sa.String(), nullable=True)

        gen["_backfill_not_null"](_add_column(column))

        assert column.server_default is None

    def test_a_required_column_with_no_default_is_refused_by_name(self) -> None:
        """A foreign key has no value the models can supply. Stopping here
        beats inventing one and failing inside alembic on someone's data."""
        gen = _generator_module()
        column = sa.Column("org_id", sa.Integer(), nullable=False)

        with pytest.raises(SystemExit) as caught:
            gen["_backfill_not_null"](_add_column(column))

        assert "llm_deployment.org_id" in str(caught.value)

    def test_a_cleared_table_takes_the_column_anyway(self) -> None:
        """The caller empties it first, so there are no rows to fail on."""
        gen = _generator_module()
        gen["CLEARED_TABLES"].add("llm_deployment")
        column = sa.Column("org_id", sa.Integer(), nullable=False)

        gen["_backfill_not_null"](_add_column(column))

        assert column.server_default is None


class TestClearingATableFirst:
    """``cleared_tables``: the DELETE that runs before the revision's DDL."""

    REVISION = 'def upgrade() -> None:\n    op.create_table("llm_deployment")\n'

    def test_the_clear_lands_above_the_ddl(self) -> None:
        out = _prepend_to_upgrade("004_ai.py", self.REVISION, ["llm_deployment"])

        assert out.index("DELETE FROM llm_deployment") < out.index("create_table")

    def test_the_clear_is_guarded_on_the_table_existing(self) -> None:
        """The same revision CREATES the table on a fresh project, where the
        clear would otherwise be the first statement to run and fail."""
        out = _prepend_to_upgrade("004_ai.py", self.REVISION, ["llm_deployment"])

        assert 'has_table("llm_deployment")' in out
