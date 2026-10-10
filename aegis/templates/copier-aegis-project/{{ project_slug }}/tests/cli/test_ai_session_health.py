"""The chat banner's health line: the app's whole health (``live_status``),
or "not available" when only the CLI's own process can be seen."""

from datetime import UTC, datetime
from io import StringIO

import pytest
from rich.console import Console

from app.cli.ai import session
from app.services.system import live_status
from app.services.system.models import SystemStatus


def _printed(monkeypatch: pytest.MonkeyPatch, note: str | None) -> StringIO:
    async def status() -> tuple[SystemStatus, str | None]:
        now = datetime.now(UTC)
        return SystemStatus(components={}, overall_healthy=True, timestamp=now), note

    out = StringIO()
    monkeypatch.setattr(live_status, "live_status", status)
    monkeypatch.setattr(session, "console", Console(file=out, width=200))
    return out


async def test_the_banner_shows_the_apps_health(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _printed(monkeypatch, None)

    await session._print_health()

    assert "%" in out.getvalue()


async def test_a_partial_walk_is_not_shown_as_the_apps_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _printed(monkeypatch, live_status.PARTIAL)

    await session._print_health()

    assert "%" not in out.getvalue()
