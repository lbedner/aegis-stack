"""What the app's database holds, as an agent's read: one read-only
statement (``query``), as Overseer's Database > Query runs it, audited.
Counted from the data, not guessed. Ships with the database component."""

from typing import Any

import pytest

from app.core.tools import get_tool, result_data
from app.services.system import db_query, db_rows, tools
from tests._audit import Recorded


@pytest.fixture
def audited(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorded = Recorded()
    monkeypatch.setattr(tools, "audit_emitter", recorded)
    return recorded.events


async def test_a_statement_answers_with_its_rows_and_is_audited(
    monkeypatch: pytest.MonkeyPatch, audited: list[dict[str, Any]]
) -> None:
    """How many job runs of each kind: one statement, its rows, as the
    Database page's Query runs it; every run is in the audit log."""
    answer = db_query.Answer(
        columns=["kind", "runs"],
        rows=[["backup", "30"], ["digest", "217"]],
        masked=frozenset(),
        more=False,
        seconds=0.004,
    )
    monkeypatch.setattr(db_query, "run", lambda sql: answer)
    sql = "SELECT kind, count(*) AS runs FROM job_execution GROUP BY kind"

    found = result_data(await tools.query(sql))

    assert found == {
        "columns": ["kind", "runs"],
        "rows": [["backup", "30"], ["digest", "217"]],
        "more": False,
    }
    assert [(a["event_type"], a["detail"], a["outcome"]) for a in audited] == [
        ("database.query", sql, "ran")
    ]
    tool = get_tool("query")
    assert tool is not None and tool.effect == "read" and tool.admin


@pytest.mark.parametrize(
    ("raised", "outcome"),
    [
        (db_query.QueryError("It returned no rows."), "refused"),
        (db_rows.ReadTooSlowError("Stopped after 5 seconds."), "stopped"),
        (db_rows.RowsHiddenError("A table's rows are the app's data."), "refused"),
    ],
)
async def test_a_statement_refused_says_why_and_is_audited_too(
    monkeypatch: pytest.MonkeyPatch,
    audited: list[dict[str, Any]],
    raised: Exception,
    outcome: str,
) -> None:
    def run(sql: str) -> None:
        raise raised

    monkeypatch.setattr(db_query, "run", run)
    with pytest.raises(ValueError, match=str(raised)):
        await tools.query("DELETE FROM job_execution")
    assert [a["outcome"] for a in audited] == [outcome]
