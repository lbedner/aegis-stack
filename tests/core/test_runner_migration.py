"""The runner's revision brings the runs meetings asked along, and names
them.

Runs were meetings' own (``meeting_action_run``) until any service could
ask one; a run now says what was asked and where (``title``, ``source``),
so a list of runs reads as questions, not moment ids. Both are a stack's
existing rows the models cannot describe, so the revision carries them.
"""

from __future__ import annotations

import sqlalchemy as sa

from aegis.core.migration_generator import RUNNER_MIGRATION
from tests.core._data_after import run_data_after

_RUN = (
    "id INTEGER PRIMARY KEY, owner_user_id INTEGER, subject_kind VARCHAR(32), "
    "subject_id VARCHAR(255), action VARCHAR(64), title VARCHAR(255), "
    "source VARCHAR(255), prompt TEXT, status VARCHAR(16), result TEXT, "
    "runner VARCHAR(255), asked_at DATETIME, claimed_at DATETIME, "
    "finished_at DATETIME"
)
_MEETINGS = (
    "CREATE TABLE meeting (id INTEGER PRIMARY KEY, owner_user_id INTEGER, "
    "title TEXT, created_at DATETIME, joined_at DATETIME)",
    "CREATE TABLE meeting_moment (id INTEGER PRIMARY KEY, meeting_id INTEGER, "
    "topic TEXT, text TEXT)",
    "INSERT INTO meeting (id, owner_user_id, title, created_at, joined_at) VALUES "
    "(1, 9, 'Weekly sync', '2026-11-10 09:00:00', '2026-11-16 18:19:52.576229'), "
    "(2, 9, NULL, '2026-11-10 09:00:00', NULL), "
    "(3, 9, 'Standup', '2026-11-12 09:00:00', NULL), "
    f"(4, 9, '{'W' * 300}', '2026-11-12 09:00:00', NULL)",
    "INSERT INTO meeting_moment (id, meeting_id, topic, text) VALUES "
    "(11, 1, NULL, 'Can the export ship?'), (12, 2, 'CSV export', 'Is it late?')",
)


def _database(*statements: str) -> sa.Connection:
    conn = sa.create_engine("sqlite://").connect()
    for statement in (f"CREATE TABLE runner_run ({_RUN})", *statements):
        conn.exec_driver_sql(statement)
    return conn


def _named(conn: sa.Connection) -> list[tuple[str, str | None, str | None]]:
    run_data_after(conn, RUNNER_MIGRATION.data_after)
    rows = conn.exec_driver_sql(
        "SELECT subject_id, title, source FROM runner_run ORDER BY id"
    )
    return [tuple(row) for row in rows]


def test_runs_meetings_asked_come_along_named() -> None:
    """The run was its moment's; it becomes its owner's, about that moment,
    called by the question and its meeting."""
    conn = _database(
        *_MEETINGS,
        "CREATE TABLE meeting_action_run (id INTEGER PRIMARY KEY, moment_id INTEGER, "
        "action VARCHAR(64), prompt TEXT, status VARCHAR(16), result TEXT, "
        "runner VARCHAR(255), asked_at DATETIME, claimed_at DATETIME, "
        "finished_at DATETIME)",
        "INSERT INTO meeting_action_run (id, moment_id, action, prompt, status) "
        "VALUES (5, 11, 'agent', '?', 'done')",
    )

    assert _named(conn) == [
        ("11", "Can the export ship?", "Meeting · Weekly sync · 2026-11-16")
    ]
    assert conn.exec_driver_sql("SELECT owner_user_id FROM runner_run").scalar() == 9


def test_runs_asked_before_runs_were_named_are_named_as_one_asked_now() -> None:
    """Its card's topic, else the question; its meeting by its calendar's
    name and the day the bot joined it (asked for, where it never did;
    a long name is cut, never its day), else by its number. A run that has a name keeps it, and one about
    something else, or about a moment that is gone, is left."""
    long = "Why? " * 80
    conn = _database(
        *_MEETINGS,
        f"INSERT INTO meeting_moment (id, meeting_id, text) VALUES (13, 3, '{long}'), "
        "(14, 4, 'Is it late?')",
        "INSERT INTO runner_run (id, subject_kind, subject_id, title, source) VALUES "
        "(1, 'moment', '11', NULL, NULL), (2, 'moment', '12', NULL, NULL), "
        "(3, 'moment', '13', NULL, NULL), (4, 'moment', '11', 'Kept', 'Here'), "
        "(5, 'issue', '11', NULL, NULL), (6, 'moment', '99', NULL, NULL), "
        "(7, 'moment', '14', NULL, NULL)",
    )

    assert _named(conn) == [
        ("11", "Can the export ship?", "Meeting · Weekly sync · 2026-11-16"),
        ("12", "CSV export", "Meeting 2"),
        ("13", long[:255], "Meeting · Standup · 2026-11-12"),
        ("11", "Kept", "Here"),
        ("11", None, None),
        ("99", None, None),
        ("14", "Is it late?", f"Meeting · {'W' * 232} · 2026-11-12"),
    ]


def test_a_stack_without_meetings_is_left_alone() -> None:
    conn = _database(
        "INSERT INTO runner_run (id, subject_kind, subject_id) VALUES (1, 'issue', '7')"
    )

    assert _named(conn) == [("7", None, None)]
