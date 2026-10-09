"""Transactions open right now (``db_transactions``): on SQLite, what each
process published (``db_activity.held``) with the container to restart;
on Postgres, ``pg_stat_activity``. Either way, past
``DATABASE_SLOW_TRANSACTION_SECONDS`` a row is trouble."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core import db_activity, series
from app.core.config import settings
from app.services.system import db_transactions, ui_runtime
from tests._fake_runtime import WORKER, FakeRuntime, use_runtime


def _held(seconds: float, host: str = WORKER.id) -> dict[str, Any]:
    began = datetime.now(UTC) - timedelta(seconds=seconds)
    return {
        "process": "worker:268",
        "host": host,
        "caller": "app/services/ai/jobs.py:44 in analyze_sentiment_job",
        "began": began.isoformat(),
        "locks": True,
    }


async def test_sqlite_names_who_holds_it_and_the_container_to_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(WORKER))
    await series.sample(ui_runtime.CONTAINERS)
    limit = settings.DATABASE_SLOW_TRANSACTION_SECONDS

    async def held() -> list[dict[str, Any]]:
        return [_held(limit + 5), _held(0.5, host="elsewhere")]

    monkeypatch.setattr(db_activity, "held", held)
    monkeypatch.setattr(db_transactions, "is_postgres", lambda: False)
    found = await db_transactions.current()
    slow, quick = found["rows"]
    assert slow["container"] == WORKER.name and slow["trouble"]
    assert slow["code"].startswith("app/services/ai/jobs.py")
    assert slow["seconds"] >= limit + 5 and slow["pid"] is None
    assert quick["container"] is None and not quick["trouble"]


async def test_postgres_reads_every_connection_and_who_blocks_whom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limit = settings.DATABASE_SLOW_TRANSACTION_SECONDS
    rows = [
        {
            "pid": 41,
            "application_name": "worker:268",
            "state": "idle in transaction",
            "xact_seconds": limit + 60,
            "wait": None,
            "blocked_by": [],
            "query": "SELECT * FROM conversation",
        },
        {
            "pid": 42,
            "application_name": "webserver:7",
            "state": "active",
            "xact_seconds": 0.5,
            "wait": "Lock: transactionid",
            "blocked_by": [41],
            "query": "UPDATE llm_model SET ...",
        },
        {
            "pid": 43,
            "application_name": "",
            "state": "idle",
            "xact_seconds": None,
            "wait": None,
            "blocked_by": [],
            "query": "",
        },
    ]

    async def activity() -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(db_transactions, "is_postgres", lambda: True)
    monkeypatch.setattr(db_transactions, "_pg_activity", activity)
    found = await db_transactions.current()
    holder, waiter, idle = found["rows"]
    assert (holder["pid"], holder["trouble"], holder["process"]) == (
        41,
        True,
        "worker:268",
    )
    assert waiter["blocked_by"] == [41] and not waiter["trouble"]
    assert idle["seconds"] is None and idle["process"] == "-"
