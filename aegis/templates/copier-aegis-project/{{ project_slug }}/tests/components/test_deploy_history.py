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
