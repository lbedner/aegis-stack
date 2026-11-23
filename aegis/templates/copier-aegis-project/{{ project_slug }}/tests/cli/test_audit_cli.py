"""``audit list``: the audit log newest first, as a table or as JSON for a
script, narrowed by kind and actor."""

import json
from unittest.mock import AsyncMock

import pytest

from app.cli import audit_cli
from app.components.database.models.audit import AuditEvent
from tests._cli import invoke

ROWS = [
    AuditEvent(
        id=2, event_type="secrets.set", actor_email="a@example.com", detail="OPENAI"
    ),
    AuditEvent(id=1, event_type="auth.login", actor_id=7),
]


@pytest.fixture
def recent(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    found = AsyncMock(return_value=ROWS)
    monkeypatch.setattr(audit_cli.audit, "recent", found)
    return found


def test_list_shows_each_row(recent: AsyncMock) -> None:
    result = invoke(["audit", "list"])
    assert result.exit_code == 0
    assert "secrets.set" in result.output and "a@example.com" in result.output
    assert "auth.login" in result.output


def test_list_as_json_narrowed(recent: AsyncMock) -> None:
    result = invoke(["audit", "list", "--json", "--kind", "auth.", "--limit", "5"])
    assert [row["event_type"] for row in json.loads(result.output)] == [
        "secrets.set",
        "auth.login",
    ]
    recent.assert_awaited_once_with(5, kind="auth.", actor=None)
