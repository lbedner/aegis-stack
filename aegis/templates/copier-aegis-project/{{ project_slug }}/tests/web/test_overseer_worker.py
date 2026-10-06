"""The Overseer Worker page: queues first (how full, whose backlog, how
well), then the Flet worker modal's task history and lifecycle."""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_worker
from app.services.system import ui_worker
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title
from tests._fake_runtime import queue_status as _queue
from tests._fake_runtime import worker_status
from tests.web.dom import none, one, select, text
from tests.web.overseer import sign_in, status_with


def _worker(*queues: ComponentStatus) -> ComponentStatus:
    return worker_status(
        *queues,
        message="TaskIQ worker infrastructure: 2 queues",
        redis_url="redis://redis:6379",
    )


WORKER = _worker(
    _queue(
        "system",
        queued_jobs=30,
        jobs_ongoing=4,
        jobs_completed=90,
        jobs_failed=0,
        oldest_waiting_seconds=3720,
    ),
    _queue(
        "load_test",
        queued_jobs=10,
        jobs_completed=10,
        jobs_failed=10,
        failure_rate_percent=50.0,
    ),
)

TASKS = [
    {
        "job_id": "abc123",
        "name": "system_health_check",
        "queue": "system",
        "status": "failed",
        "enqueued_at": "2026-09-27T10:00:00+00:00",
        "started_at": "2026-09-27T10:00:01+00:00",
        "finished_at": "2026-09-27T10:00:03+00:00",
        "duration_ms": "2000",
        "description": "Check every component.",
        "error": "Redis timed out",
    }
]

LIFECYCLE = {
    "startup": [
        {
            "name": "on_startup",
            "role": {"label": "Hook", "tone": "accent"},
            "module": "app.worker",
            "details": {},
        }
    ],
    "jobs": [
        {
            "name": "system_health_check",
            "role": {"label": "Task", "tone": "muted"},
            "module": "app.tasks",
            "details": {"Description": "Check every component."},
        }
    ],
    "shutdown": [],
}


RUNTIME = [
    {
        "worker": "a1b2:96",
        "queue": "load_test",
        "engine": "taskiq",
        "version": "0.12.6",
        "processes": "1",
        "concurrency": "100",
        "configured": "50",
        "source": "WORKER_QUEUES[load_test]",
    },
    {
        "worker": "c3d4:12",
        "queue": "system",
        "engine": "taskiq",
        "version": "0.12.6",
        "processes": "1",
        "concurrency": "10",
        "configured": "10",
        "source": "WORKER_QUEUE_DEFAULT",
    },
]


@pytest.fixture
def seen() -> dict[str, Any]:
    return {}


@pytest.fixture
def signed_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]
) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(WORKER))

    async def worker() -> ComponentStatus:
        return WORKER

    async def tasks(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        seen.update(kwargs)
        return TASKS, 60

    def lifecycle(queue: str) -> dict[str, Any]:
        seen["lifecycle"] = queue
        return LIFECYCLE

    monkeypatch.setattr(ui_worker, "load_worker", worker)
    monkeypatch.setattr(overseer_worker, "load_tasks", tasks)
    monkeypatch.setattr(overseer_worker, "load_lifecycle", lifecycle)

    async def reports() -> list[dict[str, str]]:
        return RUNTIME

    monkeypatch.setattr(ui_worker, "load_runtime", reports)
    monkeypatch.setattr(overseer_worker, "misnamed_queues", lambda: [])
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, section: str = "", query: str = "") -> str:
    url = "/overseer/components/worker" + (f"/{section}" if section else "") + query
    response = client.get(url)
    assert response.status_code == 200
    return response.text


class TestSections:
    def test_overview_then_tasks_runtime_and_lifecycle(
        self, signed_in: TestClient
    ) -> None:
        subnav = one(_get(signed_in), "#overseer-subnav")
        assert text(one(subnav, "h2")) == get_component_title("worker")
        assert [text(a) for a in select(subnav, "nav a")] == [
            "Overview",
            "Tasks",
            "Runtime",
            "Lifecycle",
            "Container",
            "Logs",
            "Settings",
        ]


class TestOverview:
    def test_the_totals_lead(self, signed_in: TestClient) -> None:
        strip = text(one(_get(signed_in), "#worker-figures"))
        # The reported 100 + 10 held, not the configured 10 + 10.
        assert "4 / 110" in strip and "4% of capacity" in strip
        assert "slots" not in strip
        assert "40" in strip  # waiting
        assert "90.9%" in strip  # 100 of 110 finished succeeded

    def test_a_card_per_queue(self, signed_in: TestClient) -> None:
        cards = select(_get(signed_in), "#worker-queues [data-queue]")
        assert [c.get("data-queue") for c in cards] == ["system", "load_test"]

    def test_slots_show_how_full_a_queue_is(self, signed_in: TestClient) -> None:
        card = one(_get(signed_in), '#worker-queues [data-queue="system"]')
        slots = select(card, ".worker-slot")
        assert len(slots) == 10
        assert len(select(card, '.worker-slot[data-busy="true"]')) == 4
        assert "4 of 10 at once" in text(card)

    def test_waiting_jobs_pile_up_as_blocks(self, signed_in: TestClient) -> None:
        card = one(_get(signed_in), '#worker-queues [data-queue="system"]')
        waiting = one(card, "[data-waiting]")
        assert "30" in text(waiting)
        assert len(select(waiting, ".worker-pile [data-lit]")) == 30
        assert "1 block" not in text(waiting)

    def test_a_big_backlog_says_what_a_block_holds(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def busy() -> ComponentStatus:
            return _worker(_queue("system", queued_jobs=342))

        monkeypatch.setattr(ui_worker, "load_worker", busy)
        waiting = one(_get(signed_in), '[data-queue="system"] [data-waiting]')
        assert len(select(waiting, ".worker-pile [data-lit]")) == 38
        assert "1 block ≈ 9 jobs" in text(waiting)

    def test_waiting_shows_how_long_the_oldest_job_has_waited(
        self, signed_in: TestClient
    ) -> None:
        """A small count can hide a job stuck for an hour; its age cannot."""
        html = _get(signed_in)
        system = text(one(html, '[data-queue="system"] [data-waiting]'))
        assert "oldest 1h 2m" in system
        load = text(one(html, '[data-queue="load_test"] [data-waiting]'))
        assert "oldest" not in load

    def test_the_header_holds_no_count_that_could_go_stale(
        self, signed_in: TestClient
    ) -> None:
        """The page header renders once; the numbers live in the stream."""
        page = next(h for h in select(_get(signed_in), "header") if select(h, "h1"))
        header = text(page)
        assert "Overview" in header and "completed" not in header

    def test_no_rate_until_something_finishes(self, signed_in: TestClient) -> None:
        html = _get(signed_in)
        assert "jobs/s" not in text(one(html, '[data-queue="system"] [data-outcome]'))

    def test_the_trend_says_when_the_backlog_drains(
        self, signed_in: TestClient
    ) -> None:
        """No history yet on a fresh page: the stream fills it in."""
        trend = one(_get(signed_in), '[data-queue="system"] [data-trend]')
        assert "measuring" in text(trend)

    def test_outcomes_show_success_and_are_flagged(self, signed_in: TestClient) -> None:
        card = one(_get(signed_in), '#worker-queues [data-queue="load_test"]')
        assert "50.0%" in text(one(card, "[data-outcome]"))
        state = one(card, "[data-state]")
        assert state.get("data-tone") == "error"  # Failing
        assert "50.0% failing" in text(state)  # the badge names its reason

    def test_each_queues_share_of_waiting_and_finished_work(
        self, signed_in: TestClient
    ) -> None:
        card = one(_get(signed_in), "#worker-distribution")
        waiting = select(card, '[data-bar="backlog"] [data-share]')
        finished = select(card, '[data-bar="work"] [data-share]')
        assert [s.get("data-share") for s in waiting] == ["75", "25"]
        assert [s.get("data-share") for s in finished] == ["82", "18"]

    def test_the_queues_stream_themselves(self, signed_in: TestClient) -> None:
        live = one(_get(signed_in), "#worker-live")
        assert live.get("sse-connect") == overseer_worker.QUEUES_EVENTS
        assert one(live, "[sse-swap]").get("sse-swap") == overseer_worker.QUEUES_EVENT
        assert live.get("hx-trigger") is None

    def test_a_broken_worker_says_why(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Queues that fail to import are an outage, shown as one."""
        from app.services.system.models import ComponentStatusType

        async def broken() -> ComponentStatus:
            return ComponentStatus(
                name="worker",
                status=ComponentStatusType.UNHEALTHY,
                message="Worker queues failed to import: system: No module named 'taskiq_redis'",
            )

        monkeypatch.setattr(ui_worker, "load_worker", broken)
        problem = text(one(_get(signed_in), "#worker-queues [data-problem]"))
        assert "taskiq_redis" in problem

    def test_no_queues_says_so(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def idle() -> ComponentStatus:
            return ComponentStatus(name="worker", message="No active workers")

        monkeypatch.setattr(ui_worker, "load_worker", idle)
        html = _get(signed_in)
        one(html, "#worker-queues [data-empty]")
        none(html, "#worker-queues [data-queue]")


class TestTrends:
    """Rate, drain and a line, from the queues sampler's kept series: the
    same for every viewer, and kept across a reconnect."""

    def test_kept_series_become_a_rate_a_drain_and_a_line(self) -> None:
        view = {"queues": [{"name": "q", "queued": 252, "completed": 148, "failed": 0}]}
        found = {
            "q:queued": [(0.0, 300.0), (10.0, 276.0), (20.0, 252.0)],
            "q:done": [(0.0, 100.0), (10.0, 124.0), (20.0, 148.0)],
        }
        q = overseer_worker.add_trends(view, found)["queues"][0]
        assert q["rate"] == 2.4
        assert q["drain"] == "drains in ~2 min"
        assert len(q["spark"].split()) == 3

    @pytest.mark.asyncio
    async def test_every_view_reads_one_health_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checks = []

        async def worker() -> ComponentStatus:
            checks.append(1)
            return WORKER

        async def no_reports() -> list[Any]:
            return []

        monkeypatch.setattr(ui_worker, "load_worker", worker)
        monkeypatch.setattr(ui_worker, "load_runtime", no_reports)
        first = await overseer_worker.queues_view()
        second = await overseer_worker.queues_view()
        assert first["queues"] == second["queues"] and len(checks) == 1


class TestQueuesStream:
    @pytest.mark.asyncio
    async def test_sends_the_queues_only_when_they_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def worker() -> ComponentStatus:
            return WORKER

        async def no_reports() -> list[Any]:
            return []  # the workers' own reports live in Redis; none here

        monkeypatch.setattr(ui_worker, "load_worker", worker)
        monkeypatch.setattr(ui_worker, "load_runtime", no_reports)
        monkeypatch.setattr(overseer_worker, "QUEUES_INTERVAL_SECONDS", 0)
        frames = [f async for f in overseer_worker.queues_events(max_frames=3)]
        events = [f for f in frames if f.startswith("event:")]
        assert len(events) == 1
        assert events[0].startswith(f"event: {overseer_worker.QUEUES_EVENT}\n")


class TestTasks:
    def test_rows_and_failed_detail(self, signed_in: TestClient) -> None:
        html = _get(signed_in, "tasks")
        row = select(html, "tbody tr:not([data-detail])")[0]
        assert "system_health_check" in text(row) and "2.0s" in text(row)
        assert one(row, "[data-tone]").get("data-tone") == "error"
        detail = text(one(html, "tr[data-detail]"))
        assert "Redis timed out" in detail and "abc123" in detail

    def test_filters_by_queue_and_status(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        html = _get(signed_in, "tasks", "?queue=system&status=failed")
        assert seen["queue"] == "system" and seen["status"] == "failed"
        current = [
            text(a)
            for a in select(html, 'a[aria-current="page"]')
            if a.get("href", "").find("tasks") >= 0
        ]
        assert "system" in current and "Failed" in current

    def test_every_queue_by_default(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        _get(signed_in, "tasks")
        assert seen["queue"] is None and seen["status"] is None

    def test_pages(self, signed_in: TestClient, seen: dict[str, Any]) -> None:
        html = _get(signed_in, "tasks", "?page=2&queue=system")
        assert seen["offset"] == overseer_worker.PAGE_SIZE
        nxt = one(html, 'nav[aria-label="Pagination"] a[rel="next"]')
        assert "queue=system" in nxt.get("href")


class TestRuntime:
    """What each worker process is really running with, as it reported."""

    def test_a_card_per_reporting_process(self, signed_in: TestClient) -> None:
        cards = select(_get(signed_in, "runtime"), "[data-runtime]")
        assert [c.get("data-runtime") for c in cards] == ["a1b2:96", "c3d4:12"]
        facts = text(cards[0])
        assert "taskiq 0.12.6" in facts and "load_test" in facts

    def test_a_worker_off_its_setting_is_flagged(self, signed_in: TestClient) -> None:
        """Running 100 when the settings ask 50: started outside the entrypoint."""
        load, system = select(_get(signed_in, "runtime"), "[data-runtime]")
        warning = text(one(load, "[data-mismatch]"))
        assert "100" in warning and "WORKER_QUEUES[load_test]" in warning
        none(system, "[data-mismatch]")
        assert "10 per process" in text(system)
        assert "WORKER_QUEUE_DEFAULT" in text(system)

    def test_settings_naming_a_missing_queue_are_flagged(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(overseer_worker, "misnamed_queues", lambda: ["sytem"])
        banner = text(one(_get(signed_in, "runtime"), "[data-misnamed]"))
        assert "sytem" in banner

    def test_no_reports_says_how_to_get_one(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def nothing() -> list[dict[str, str]]:
            return []

        monkeypatch.setattr(ui_worker, "load_runtime", nothing)
        one(_get(signed_in, "runtime"), "[data-empty]")


class TestReportedCapacity:
    def test_the_overview_counts_what_the_workers_really_hold(
        self, signed_in: TestClient
    ) -> None:
        """Reported limits beat the configured one: 100 held is 100."""
        card = one(_get(signed_in), '#worker-queues [data-queue="load_test"]')
        assert "of 100 at once" in text(card)


class TestLifecycle:
    def test_steps_for_the_picked_queue(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        html = _get(signed_in, "lifecycle", "?queue=load_test")
        assert seen["lifecycle"] == "load_test"
        jobs = one(html, "#lifecycle-jobs")
        assert "system_health_check" in text(jobs) and "Task" in text(jobs)
        one(html, "#lifecycle-startup")

    def test_the_first_queue_by_default(
        self, signed_in: TestClient, seen: dict[str, Any]
    ) -> None:
        _get(signed_in, "lifecycle")
        assert seen["lifecycle"] == "system"
