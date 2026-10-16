"""Search's index on SQLite: an FTS5 table beside the transcript lines and
one beside the note items, each over its table's own text (no copy), kept
by triggers as lines are captioned, grow and are deleted, and as notes are
written again.

No model can describe a virtual table, so neither ``create_all`` nor a
revision makes these: every ``create_all`` on SQLite (a SQLite stack's
startup, the test suite's) makes any that are missing, filling a new one
from what is already kept, and puts back any trigger a table rebuilt
without (the listener below; ``models`` imports this so it is there
whenever the tables are). Postgres needs no table: its meetings revision
adds a GIN index over each text column.
"""

from typing import Any

from sqlalchemy import Connection, event
from sqlmodel import SQLModel

LINES = "meeting_line_search"
NOTES = "meeting_note_search"
# English stems ("pricing" finds "priced"), as Postgres's 'english' does.
TOKENIZE = "porter unicode61"


def _index(search: str, table: str) -> tuple[str, list[str]]:
    """The FTS5 table over ``table``'s ``text`` (rowid its ``id``), and the
    triggers that keep it: (the table's DDL, the triggers' DDL)."""
    create = f"""CREATE VIRTUAL TABLE {search} USING fts5(
        text, content='{table}', content_rowid='id', tokenize='{TOKENIZE}')"""
    triggers = [
        f"""CREATE TRIGGER IF NOT EXISTS {search}_insert
            AFTER INSERT ON {table} BEGIN
            INSERT INTO {search} (rowid, text) VALUES (new.id, new.text);
        END""",
        f"""CREATE TRIGGER IF NOT EXISTS {search}_delete
            AFTER DELETE ON {table} BEGIN
            INSERT INTO {search} ({search}, rowid, text)
            VALUES ('delete', old.id, old.text);
        END""",
        f"""CREATE TRIGGER IF NOT EXISTS {search}_update
            AFTER UPDATE OF text ON {table} BEGIN
            INSERT INTO {search} ({search}, rowid, text)
            VALUES ('delete', old.id, old.text);
            INSERT INTO {search} (rowid, text) VALUES (new.id, new.text);
        END""",
    ]
    return create, triggers


_INDEXES = {
    LINES: _index(LINES, "meeting_transcript_line"),
    NOTES: _index(NOTES, "meeting_note_item"),
}


def create_search_tables(_target: Any, connection: Connection, **_: Any) -> None:
    """Make the search tables a SQLite database lacks, once the meetings'
    own tables are there, each filled from what is already kept, and their
    triggers wherever one is missing (a rebuilt table loses its own). A
    ``MetaData`` ``after_create`` listener: it runs on every ``create_all``,
    and does nothing where there is nothing to make."""
    if connection.dialect.name != "sqlite":
        return
    have = set(
        connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).scalars()
    )
    if not {"meeting_transcript_line", "meeting_note_item"} <= have:
        return
    for search, (create, triggers) in _INDEXES.items():
        made = search not in have
        if made:
            connection.exec_driver_sql(create)
        for trigger in triggers:
            connection.exec_driver_sql(trigger)
        if made:
            connection.exec_driver_sql(
                f"INSERT INTO {search} ({search}) VALUES ('rebuild')"
            )


event.listen(SQLModel.metadata, "after_create", create_search_tables)
