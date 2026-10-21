"""What the code's models expect that the database lacks (aegis-stack#1789).

A rolling deploy brings the database up to the new code before anything
restarts on it, by running the webserver's own boot step from the new
image. That step logs a failed migration and carries on, as a boot must:
so the deploy asks ``schema_gaps`` afterwards, and restarts nothing onto
a gap.
"""

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

from app.components.backend.startup.database_init import schema_gaps


def _expected() -> MetaData:
    """The code's models: two tables, one with a column the database
    has not been given."""
    metadata = MetaData()
    Table(
        "ledger",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("key", String),
    )
    Table("payee", metadata, Column("id", Integer, primary_key=True))
    return metadata


def test_a_database_with_everything_has_no_gap() -> None:
    engine = create_engine("sqlite://")
    _expected().create_all(engine)
    assert schema_gaps(engine, _expected()) == {}


def test_a_missing_column_and_a_missing_table_are_named() -> None:
    engine = create_engine("sqlite://")
    behind = MetaData()
    Table("ledger", behind, Column("id", Integer, primary_key=True))
    behind.create_all(engine)
    assert schema_gaps(engine, _expected()) == {"ledger": {"key"}, "payee": set()}
