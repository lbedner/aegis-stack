"""The Overseer Scheduler page: the Flet scheduler modal's Jobs and History."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_scheduler
from app.core.db import get_async_db
from app.services.system.models import ComponentStatus
from tests.web.dom import none, one, select, text
from tests.web.overseer import sign_in, status_with

SOON = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
PAST = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
# History must read on the request's own session: on SQLite a second one
# waits on its write lock and fails "database is locked" (seen live).
REQUEST_SESSION = object()

METADATA: dict[str, Any] = {
    "total_tasks": 2,
    "active_tasks": 2,
    "paused_tasks": 0,
    "scheduler_state": "running",
    "upcoming_tasks": [
        {
            "job_id": "database_backup",
            "name": "Daily Database Backup",
            "next_run": SOON,
            "schedule": "Cron: hour=2, minute=0, second=0",
            "function": "app.services.system.backup:backup_database_job",
            "description": "Scheduled database backup job.",
        },
        {
            "job_id": "heartbeat",
            "name": "Scheduler Heartbeat",
            "next_run": PAST,
            "schedule": "Every 15s",
            "function": "app.components.scheduler.heartbeat:touch",
            "description": None,
        },
    ],
}

EXECUTIONS = [
    {
        "job_id": "database_backup",
        "job_name": "Daily Database Backup",
        "status": "failed",
        "duration_ms": 1500,
        "started_at": PAST,
        "scheduled_run_time": PAST,
        "finished_at": PAST,
        "error_message": "disk full",
    },
]


@pytest.fixture
def seen() -> dict[str, Any]:
    return {}


@pytest.fixture
def signed_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]
) -> Generator[TestClient]:
    scheduler = ComponentStatus(
        name="scheduler", message="Scheduler running with 2 tasks", metadata=METADATA
    )
    sign_in(app, monkeypatch, status_with(scheduler))

    async def executions(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        seen.update(kwargs)
        return EXECUTIONS, 60

    async def request_session() -> Any:
        return REQUEST_SESSION

    monkeypatch.setattr(overseer_scheduler, "load_executions", executions)

    async def no_stats(**_: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(overseer_scheduler, "load_job_stats", no_stats)
    app.dependency_overrides[get_async_db] = request_session
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, section: str = "", query: str = "") -> str:
    url = "/overseer/components/scheduler" + (f"/{section}" if section else "") + query
    response = client.get(url)
    assert response.status_code == 200
    return response.text


def _rows(html: str) -> list[Any]:
    return select(html, "tbody tr:not([data-detail])")


class TestSections:
    def test_overview_then_jobs_and_history(self, signed_in: TestClient) -> None:
        subnav = one(_get(signed_in), "#overseer-subnav")
        assert text(one(subnav, "h2")) == "Scheduler"
        assert [text(a) for a in select(subnav, "nav a")] == [
            "Overview",
            "Jobs",
            "History",
            "Container",
            "Logs",
            "Settings",
        ]


class TestOverview:
    """The counts and state live in the clock's own style, not in cards."""

    def test_the_legend_sums_up_the_jobs(self, signed_in: TestClient) -> None:
        html = _get(signed_in)
        summary = text(one(html, "#scheduler-summary"))
        assert "2 jobs" in summary and "2 active" in summary and "0 paused" in summary
        none(html, "#scheduler-figures")
        none(html, "#card-current-status")

    def test_the_hub_says_whether_it_is_running(self, signed_in: TestClient) -> None:
        hub = one(_get(signed_in), "#scheduler-clock [data-hub=live]")
        assert "running" in text(hub)
        none(hub, ".text-aegis-amber")


class TestClock:
    """The Overview is the landing page's scheduler clock, on live data."""

    def test_cron_jobs_are_dots_on_the_dial_and_rows_in_the_legend(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in)
        clock = one(html, "#scheduler-clock")
        dots = select(clock, ".clock__job")
        assert len(dots) == 1  # the backup; the 15s heartbeat is not a dot
        legend = [text(n) for n in select(html, "#scheduler-legend [data-job]")]
        assert legend == ["Daily Database Backup"]
        assert "every 15s" in text(one(html, "#scheduler-legend [data-intervals]"))
        one(html, "#scheduler-clock .clock__band--live")

    def test_the_hand_runs_on_real_time(self, signed_in: TestClient) -> None:
        hand = one(_get(signed_in), "#scheduler-clock .clock__hand")
        assert hand.get("style").startswith("animation-delay: -")

    def test_history_draws_coloured_arcs_on_the_request_session(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def stats(*, db: Any, job_ids: list[str]) -> dict[str, Any]:
            seen["db"], seen["ids"] = db, job_ids
            return {
                "database_backup": {
                    "avg_duration_ms": 1_800_000,
                    "last_run": {"status": "failed", "duration_ms": 1_800_000},
                }
            }

        monkeypatch.setattr(overseer_scheduler, "load_job_stats", stats)
        monkeypatch.setattr(overseer_scheduler, "persistent", lambda: True)
        html = _get(signed_in)
        arc = one(html, "#scheduler-clock path.clock__arc")
        assert "clock__arc--red" in arc.get("class")
        assert seen["db"] is REQUEST_SESSION
        assert "database_backup" in seen["ids"]

    def test_the_dial_names_its_timezone_and_store(self, signed_in: TestClient) -> None:
        hub = text(one(_get(signed_in), "#scheduler-clock [data-hub=live]"))
        assert "UTC" in hub
        assert "store" in hub


class TestMovingJobs:
    """Jobs are picked and dragged; the hand always shows now."""

    def test_the_hand_is_not_draggable(self, signed_in: TestClient) -> None:
        html = _get(signed_in)
        assert (
            one(html, "#scheduler-clock-view")
            .get("x-data")
            .startswith("schedulerClock(")
        )
        clock = one(html, "#scheduler-clock")
        assert clock.get("@pointerdown") is None
        assert one(clock, ".clock__hand").get(":style") is None

    def test_each_job_is_a_selectable_slot_at_its_angle(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in)
        slot = one(html, "#scheduler-clock .clock__slot")
        assert slot.get("style") == f"--angle: {slot.get('data-angle')}deg"
        assert (
            one(slot, "button.clock__job")
            .get("aria-label")
            .startswith("Daily Database Backup")
        )
        row = one(html, "#scheduler-legend [data-job-id]")
        assert row.get("data-job-id") == slot.get("data-job-id")

    def test_hovering_a_job_previews_it_and_says_it_can_be_moved(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in)
        hub = one(html, "#scheduler-clock [data-hub=hover]")
        assert "click" in text(hub)
        dot = one(html, "#scheduler-clock .clock__job")
        row = one(html, "#scheduler-legend [data-job-id]")
        for el in (dot, row):
            assert el.get("@mouseenter") and el.get("@mouseleave")

    def test_clicking_away_returns_to_neutral(self, signed_in: TestClient) -> None:
        html = _get(signed_in)
        view = one(html, "#scheduler-clock-view")
        assert view.get("@click.outside") == "neutral()"
        assert view.get("@keydown.escape") == "neutral()"
        assert one(html, "#scheduler-clock").get("@click") == "clickDial($event)"

    def test_a_moved_job_can_be_reset(self, signed_in: TestClient) -> None:
        one(_get(signed_in), "#scheduler-clock button[data-reset]")

    def test_a_moved_job_says_it_is_only_a_preview(self, signed_in: TestClient) -> None:
        note = one(_get(signed_in), "#scheduler-clock [data-hub=move] [data-preview]")
        assert note.get("x-show") == "isMoved()"
        assert "not saved" in text(note)


class TestJobs:
    def test_rows_read_like_flet(self, signed_in: TestClient) -> None:
        rows = _rows(_get(signed_in, "jobs"))
        cells = [[text(td) for td in row.cssselect("td")[1:]] for row in rows]
        assert cells[0][0] == "Daily Database Backup"
        assert cells[0][1].startswith("in ")
        assert cells[0][2] == "Daily at 2:00 AM UTC"
        assert cells[0][3] == "Active"
        assert cells[1][1] == "Past due"

    def test_past_due_job_is_flagged(self, signed_in: TestClient) -> None:
        badge = one(_rows(_get(signed_in, "jobs"))[1], "[data-tone]")
        assert badge.get("data-tone") == "warn"

    def test_detail_shows_description_function_and_run_now(
        self, signed_in: TestClient
    ) -> None:
        detail = select(_get(signed_in, "jobs"), "tr[data-detail]")[0]
        assert "Scheduled database backup job." in text(detail)
        assert "app.services.system.backup:backup_database_job" in text(detail)
        run = one(detail, "button[hx-get]")
        assert (
            run.get("hx-get")
            == "/partials/overseer/scheduler/confirm/run/database_backup"
        )


class TestJobDetail:
    """Each job's run stats and a way to its history, beyond the Flet modal."""

    def test_shows_run_stats_from_the_request_session(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def stats(*, db: Any, job_ids: list[str]) -> dict[str, Any]:
            seen["db"] = db
            return {
                "database_backup": {
                    "total_runs": 12,
                    "success_rate": 91.7,
                    "avg_duration_ms": 1500,
                    "last_run": {"status": "failed", "started_at": PAST},
                }
            }

        monkeypatch.setattr(overseer_scheduler, "load_job_stats", stats)
        monkeypatch.setattr(overseer_scheduler, "persistent", lambda: True)
        backup, heartbeat = select(_get(signed_in, "jobs"), "tr[data-detail]")
        facts = text(one(backup, "[data-stats]"))
        assert "12" in facts and "91.7%" in facts and "1.5s" in facts
        assert "Failed" in facts
        assert "No runs yet" in text(one(heartbeat, "[data-stats]"))
        assert seen["db"] is REQUEST_SESSION

    def test_links_to_its_history(self, signed_in: TestClient) -> None:
        detail = select(_get(signed_in, "jobs"), "tr[data-detail]")[0]
        link = one(detail, "a[data-history]")
        assert (
            link.get("href")
            == "/overseer/components/scheduler/history?job=database_backup"
        )


class TestRunNow:
    def test_confirmation_calls_the_api(self, signed_in: TestClient) -> None:
        response = signed_in.get(
            "/partials/overseer/scheduler/confirm/run/database_backup"
        )
        assert response.status_code == 200
        button = one(response.text, "button[data-api-done]")
        assert button.get("hx-post") == "/api/v1/scheduler/jobs/database_backup/run"
        assert "border-aegis-teal" in button.get("class")  # running is not destructive
        assert "Daily Database Backup" in text(one(response.text, "p"))

    def test_unknown_job_is_404(self, signed_in: TestClient) -> None:
        assert (
            signed_in.get("/partials/overseer/scheduler/confirm/run/nope").status_code
            == 404
        )


class TestHistory:
    def test_rows_and_failed_detail(self, signed_in: TestClient) -> None:
        html = _get(signed_in, "history")
        row = _rows(html)[0]
        assert "Daily Database Backup" in text(row)
        assert "1.5s" in text(row)
        assert one(row, "[data-tone]").get("data-tone") == "error"
        assert "disk full" in text(one(html, "tr[data-detail]"))

    def test_reads_on_the_request_session(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        _get(signed_in, "history")
        assert seen["db"] is REQUEST_SESSION

    def test_status_filter_is_passed_through(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        html = _get(signed_in, "history", "?status=failed")
        assert seen["status"] == "failed"
        chip = one(html, 'a[aria-current="page"][href*="status="]')
        assert text(chip) == "Failed"

    def test_pages_through_the_history(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        html = _get(signed_in, "history", "?page=2")
        assert seen["offset"] == overseer_scheduler.PAGE_SIZE
        one(html, 'nav[aria-label="Pagination"] a[rel="prev"]')
        one(html, 'nav[aria-label="Pagination"] a[rel="next"]')

    def test_filters_to_one_job_and_keeps_it_across_pages_and_status(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        html = _get(signed_in, "history", "?job=database_backup&status=failed")
        assert seen["job_id"] == "database_backup"
        assert seen["status"] == "failed"
        chip = one(html, "[data-job-filter]")
        assert "Daily Database Backup" in text(chip)
        assert one(chip, "a").get("href") == (
            "/overseer/components/scheduler/history?status=failed"
        )
        next_page = one(html, 'nav[aria-label="Pagination"] a[rel="next"]')
        assert "job=database_backup" in next_page.get("href")
        all_status = select(html, 'nav[aria-label="Filter by status"] a')[0]
        assert all_status.get("href").endswith("?job=database_backup")

    def test_without_a_job_filter_every_job_is_read(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        html = _get(signed_in, "history")
        assert seen["job_id"] is None
        none(html, "[data-job-filter]")

    def test_without_history_it_says_so(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def nothing(**_: Any) -> tuple[list[dict[str, Any]], int]:
            return [], 0

        monkeypatch.setattr(overseer_scheduler, "load_executions", nothing)
        html = _get(signed_in, "history")
        none(html, "tbody tr")
        one(html, "[data-empty]")


class TestHistoryWithoutPersistence:
    def test_says_history_needs_a_persistent_backend(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the in-memory backend there is no execution log to read."""

        monkeypatch.setattr(overseer_scheduler, "persistent", lambda: False)
        empty = one(_get(signed_in, "history"), "[data-empty]")
        assert "persistent" in text(empty)
