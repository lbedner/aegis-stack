"""Meetings search's index, in the meetings revision.

On Postgres the revision adds a GIN index over the English full-text
vector of the transcript's lines and of the note items, the expressions
the search matches on. SQLite needs none
from a revision (its FTS5 tables come with ``create_all``), and every
revision replays onto a scratch SQLite, so there it does nothing.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from aegis.core.migration_generator import MEETINGS_MIGRATION, _place_data_statements


def test_the_index_follows_the_tables_it_indexes(tmp_path: Path) -> None:
    revision = tmp_path / "005_meetings.py"
    revision.write_text(
        '"""meetings"""\n'
        "def upgrade() -> None:\n"
        '    op.create_table("meeting_transcript_line")\n'
        "\n\ndef downgrade() -> None:\n    pass\n"
    )

    _place_data_statements(tmp_path, ["meetings"], [revision])

    upgrade = revision.read_text().partition("def downgrade")[0]
    assert upgrade.index("create_table") < upgrade.index("to_tsvector")
    assert "USING gin" in upgrade
    assert "ON meeting_note_item" in upgrade


def test_on_sqlite_it_does_nothing() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE meeting_transcript_line (id INTEGER PRIMARY KEY, text TEXT)"
        )
        namespace: dict[str, object] = {
            "op": Operations(MigrationContext.configure(conn)),
            "sa": sa,
        }
        body = MEETINGS_MIGRATION.data_after
        exec(compile(f"def upgrade():\n{body}\n", "revision", "exec"), namespace)
        namespace["upgrade"]()  # type: ignore[operator]

        assert sa.inspect(conn).get_indexes("meeting_transcript_line") == []
