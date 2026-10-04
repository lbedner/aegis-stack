"""Deploy history: one row per build that went live.

Two writers fill the same row, keyed by the build id. The app records a new
build when it starts, which covers every way code reaches the server; the
deployer adds what only it knows (who, from where, health, the backup, a
rollback) through ``deploy record``. Tests run on the app-owned database the
suite redirects ``get_async_session`` to.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlmodel import select

from app.components.backend.startup import deploy_history as startup
from app.components.deploy import history
from app.components.deploy.models import Deployment
from app.core.config import Settings, settings
from app.core.db import get_async_session
from tests._cli import invoke

# Each test writes a row and reads it back; the repeats are the scenario.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)

BUILD = "a1b2c3d"


@pytest.fixture(autouse=True)
async def _empty_history() -> AsyncIterator[None]:
    """The suite's database outlives a test; each one starts with no rows."""
    yield
    async with get_async_session() as db:
        for row in (await db.exec(select(Deployment))).all():
            await db.delete(row)
        await db.commit()


async def _rows() -> list[Deployment]:
    async with get_async_session() as db:
        return list((await db.exec(select(Deployment))).all())


async def test_a_new_build_is_recorded_once_when_it_starts() -> None:
    await history.record_start(BUILD)
    await history.record_start(BUILD)

    rows = await _rows()
    assert [(row.build_id, row.finished_at) for row in rows] == [(BUILD, None)]


async def test_a_dev_build_is_not_recorded() -> None:
    await history.record_start(Settings.model_fields["BUILD_ID"].default)

    assert await _rows() == []


async def test_the_deployer_fills_in_what_only_it_knows() -> None:
    await history.record_start(BUILD)
    started = (await _rows())[0].started_at

    await history.record_deploy(
        BUILD,
        deployed_by="Ada <ada@example.org>",
        deployed_from="ada-laptop",
        health="passed",
        backup="20261003_220000",
    )

    (row,) = await _rows()
    assert row.deployed_by == "Ada <ada@example.org>"
    assert row.deployed_from == "ada-laptop"
    assert row.health == "passed"
    assert row.backup == "20261003_220000"
    assert row.started_at == started
    assert row.finished_at is not None


async def test_a_deploy_the_app_never_saw_start_still_gets_a_row() -> None:
    """The new build failed its health check before its startup wrote."""
    await history.record_deploy(BUILD, health="failed")

    (row,) = await _rows()
    assert (row.build_id, row.health) == (BUILD, "failed")


async def test_a_rollback_names_the_build_now_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a rollback the restored build is the one serving, so the app
    names it itself."""
    monkeypatch.setitem(settings.__dict__, "BUILD_ID", "9f8e7d6")

    await history.record_deploy(BUILD, health="failed", rolled_back=True)

    (row,) = await _rows()
    assert row.rolled_back_to == "9f8e7d6"


async def test_the_webserver_records_its_own_build_as_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(settings.__dict__, "BUILD_ID", BUILD)

    await startup.startup_hook()

    assert [row.build_id for row in await _rows()] == [BUILD]


def test_deploy_record_passes_what_the_deployer_knows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def capture(build_id: str, **fields: Any) -> None:
        seen.update(build_id=build_id, **fields)

    monkeypatch.setattr(history, "record_deploy", capture)

    result = invoke(
        [
            "deploy",
            "record",
            "--build",
            BUILD,
            "--by",
            "Ada <ada@example.org>",
            "--from",
            "ada-laptop",
            "--health",
            "passed",
            "--backup",
            "20261003_220000",
            "--rolled-back",
        ]
    )

    assert result.exit_code == 0, result.output
    assert seen == {
        "build_id": BUILD,
        "deployed_by": "Ada <ada@example.org>",
        "deployed_from": "ada-laptop",
        "health": "passed",
        "backup": "20261003_220000",
        "rolled_back": True,
    }


async def test_the_history_reads_newest_first() -> None:
    for build in ("aaa1111", "bbb2222", "ccc3333"):
        await history.record_start(build)
    assert [row.build_id for row in await history.recent(limit=2)] == [
        "ccc3333",
        "bbb2222",
    ]


async def test_overseer_shows_each_deploy_and_who_made_the_live_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overseer > Deployments (``ui_deployments``): the history, newest first,
    and on Now who deployed the build that is running."""
    from app.services.system import ui_deployments

    await history.record_start("aaa1111")
    await history.record_deploy(
        "aaa1111",
        deployed_by="Ada <ada@example.org>",
        deployed_from="ada-laptop",
        health="passed",
        backup="20261003_020000",
    )
    # bbb2222 failed its health check and was rolled back: aaa1111 runs again.
    monkeypatch.setattr(settings, "BUILD_ID", "aaa1111")
    await history.record_deploy(
        "bbb2222", deployed_by="Ada", health="failed", rolled_back=True
    )

    view = await ui_deployments.history()
    assert view["note"] is None
    first, second = view["rows"]
    assert (first["build"], first["health"], first["rollback"]) == (
        "bbb2222",
        "failed",
        "Back to aaa1111",
    )
    assert (second["by"], second["from"], second["backup"]) == (
        "Ada <ada@example.org>",
        "ada-laptop",
        "20261003_020000",
    )
    now = dict(await ui_deployments.now())
    assert now["Deployed by"] == "Ada <ada@example.org> from ada-laptop"


async def test_a_history_it_cannot_read_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A build that adds the table runs before it is migrated: Overseer says
    so instead of failing the page."""
    from sqlalchemy.exc import OperationalError

    from app.services.system import ui_deployments

    async def missing(*args: Any, **kwargs: Any) -> Any:
        raise OperationalError("SELECT", {}, Exception("no such table: deployment"))

    monkeypatch.setattr(history, "recent", missing)
    monkeypatch.setattr(history, "get", missing)
    view = await ui_deployments.history()
    assert view["rows"] == [] and "no such table" in view["note"]
    assert "Deployed by" not in dict(await ui_deployments.now())
