"""Everything done to the server, recorded (aegis-stack#1482).

``deployment`` says which builds went live; ``deploy_event`` keeps the rest:
each backup, rollback, upload, off-site copy and restore drill, who did it,
from where, and how it went. ``aegis`` writes them through ``deploy event``
(over SSH, as it writes ``deploy record``); jobs in the app call
``record_event`` directly.
"""

import json
from typing import Any

import pytest

from app.components.deploy import history
from app.components.deploy.models import DeployEvent
from tests._cli import invoke
from tests._deploy_events import no_deploy_events  # noqa: F401

pytestmark = [
    pytest.mark.queryspy(allow_n_plus_one=True),
    pytest.mark.usefixtures("no_deploy_events"),
]


async def test_events_are_kept_and_read_back_newest_first() -> None:
    await history.record_event(
        "backup",
        "ok",
        summary="Backed up 2026-10-16_014324",
        actor="Ada <ada@example.org>",
        origin="ada-laptop",
        detail={"backup": "2026-10-16_014324"},
    )
    await history.record_event("restore-drill", "failed", summary="2 files missing")
    newest, older = await history.recent_events()
    assert (newest.kind, newest.outcome) == ("restore-drill", "failed")
    assert (older.actor, older.origin) == ("Ada <ada@example.org>", "ada-laptop")
    assert older.detail == {"backup": "2026-10-16_014324"}
    assert older.finished_at is not None


async def test_the_latest_of_a_kind() -> None:
    await history.record_event("offsite", "ok", summary="first")
    await history.record_event("backup", "ok", summary="other")
    await history.record_event("offsite", "failed", summary="second")
    latest = await history.latest_event("offsite")
    assert latest is not None and latest.summary == "second"
    assert await history.latest_event("restore-drill") is None


def test_aegis_records_one_through_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """What ``aegis`` sends, as one JSON argument (it quotes each)."""
    seen: list[dict[str, Any]] = []

    async def capture(kind: str, outcome: str, **fields: Any) -> None:
        seen.append({"kind": kind, "outcome": outcome, **fields})

    monkeypatch.setattr(history, "record_event", capture)
    sent = {
        "kind": "upload-storage",
        "outcome": "ok",
        "summary": "Brought 317 files",
        "actor": "Ada",
        "origin": "ada-laptop",
        "started_at": "2026-10-16T21:40:00+00:00",
        "detail": {"files": 317},
    }
    result = invoke(["deploy", "event", json.dumps(sent)])
    assert result.exit_code == 0, result.output
    (got,) = seen
    assert got["kind"] == "upload-storage" and got["detail"] == {"files": 317}
    assert got["started_at"].isoformat() == "2026-10-16T21:40:00+00:00"


def test_the_events_as_json_for_the_dev_overseer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The protocol's ``history`` reads them on the server, the last line
    of ``deploy events`` (whatever the app logged before it)."""

    async def recent_events(limit: int = 50) -> list[DeployEvent]:
        return [DeployEvent(kind="backup", outcome="ok", summary="Backed up")]

    monkeypatch.setattr(history, "recent_events", recent_events)
    result = invoke(["deploy", "events"])
    assert result.exit_code == 0, result.output
    (row,) = json.loads(result.output.strip().splitlines()[-1])
    assert (row["kind"], row["summary"]) == ("backup", "Backed up")
