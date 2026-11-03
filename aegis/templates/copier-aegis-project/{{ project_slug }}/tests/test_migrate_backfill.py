"""A required column added to a table that already has rows gets the
model's own default for them (``migrate_backfill.backfill_not_null``); the pure
cases are covered from the framework (``tests/core/test_not_null_backfill``),
these need the project's models."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("alembic", reason="no database component in this stack")

import sqlalchemy as sa  # noqa: E402
from sqlmodel import JSON, Column, Field, SQLModel  # noqa: E402

from alembic.operations import ops  # noqa: E402


@pytest.mark.parametrize(("factory", "backfill"), [(list, "'[]'"), (dict, "'{}'")])
def test_a_json_fields_factory_backfills_its_empty_value(
    factory: type, backfill: str
) -> None:
    """``sa_column=Column(JSON, nullable=False)`` with a ``default_factory``:
    SQLModel hands the Column through with no default, so the factory is
    read from the model's field."""
    migrate_backfill: Any = pytest.importorskip("app.cli.migrate_backfill")

    class Shelf(SQLModel, table=True):
        __tablename__ = f"shelf_{factory.__name__}"
        id: int | None = Field(default=None, primary_key=True)
        tags: Any = Field(
            default_factory=factory, sa_column=Column(JSON, nullable=False)
        )

    column = Shelf.__table__.c.tags  # type: ignore[attr-defined]
    try:
        migrate_backfill.backfill_not_null(ops.AddColumnOp(Shelf.__tablename__, column))
    finally:
        SQLModel.metadata.remove(Shelf.__table__)  # type: ignore[attr-defined]

    assert isinstance(column.server_default, sa.DefaultClause)
    assert str(column.server_default.arg) == backfill
