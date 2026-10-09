"""Ending a Postgres connection from Overseer: an admin (anyone, without
auth) ends one of this database's connections, and every attempt is
audited. SQLite has nothing to end: its holder's container restarts."""

import pytest
from fastapi.testclient import TestClient

from app.services.system import db_transactions
from tests._audit import ADMIN, Recorded, as_admin, recording

URL = "/api/v1/database/connections/{pid}/end"


@pytest.fixture
def audit(client: TestClient) -> Recorded:
    as_admin(client)
    return recording(client)


def _postgres(monkeypatch: pytest.MonkeyPatch, live: set[int]) -> list[int]:
    ended: list[int] = []

    async def end(pid: int) -> bool:
        ended.append(pid)
        return pid in live

    monkeypatch.setattr(db_transactions, "is_postgres", lambda: True)
    monkeypatch.setattr(db_transactions, "end", end)
    return ended


def test_an_admin_ends_a_connection_and_it_is_audited(
    client: TestClient, audit: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    ended = _postgres(monkeypatch, {41})
    response = client.post(URL.format(pid=41))
    assert response.status_code == 200 and response.json() == {"ended": 41}
    assert ended == [41]
    (event,) = audit.events
    assert event["event_type"] == "database.connection_end"
    assert (event["actor_email"], event["pid"], event["outcome"]) == (
        ADMIN.email,
        41,
        "ended",
    )


def test_a_connection_that_is_not_this_databases_is_404_and_audited(
    client: TestClient, audit: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    _postgres(monkeypatch, set())
    assert client.post(URL.format(pid=99)).status_code == 404
    assert audit.events[0]["outcome"] == "refused"


def test_sqlite_has_no_connection_to_end(
    client: TestClient, audit: Recorded, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_transactions, "is_postgres", lambda: False)
    assert client.post(URL.format(pid=41)).status_code == 409
    assert audit.events[0]["outcome"] == "refused"
