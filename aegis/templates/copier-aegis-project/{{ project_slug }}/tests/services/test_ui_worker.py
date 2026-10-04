"""What the worker views show, for Flet and the web frontend alike: each
queue's state, how full it is, and its share of the work."""

from typing import Any

import pytest

from app.services.system import ui_worker
from app.services.system.models import ComponentStatus


def _queue(name: str, message: str = "", **meta: Any) -> ComponentStatus:
    base = {
        "worker_alive": True,
        "queued_jobs": 0,
        "jobs_ongoing": 0,
        "jobs_completed": 0,
        "jobs_failed": 0,
        "failure_rate_percent": 0.0,
        "consumer_count": 1,
        "max_concurrency": 10,
        "timeout_seconds": 300,
        "description": f"{name} jobs",
    }
    return ComponentStatus(name=name, message=message, metadata=base | meta)


def _worker(*queues: ComponentStatus) -> ComponentStatus:
    group = ComponentStatus(
        name="queues", message="", sub_components={q.name: q for q in queues}
    )
    return ComponentStatus(name="worker", message="", sub_components={"queues": group})


class TestQueueState:
    def test_offline_without_a_consumer(self) -> None:
        assert ui_worker.queue_state(_queue("q", worker_alive=False)) == (
            "Offline",
            "red",
        )

    def test_a_queue_with_no_tasks_is_grey(self) -> None:
        queue = _queue("q", "q: configured - no functions defined", worker_alive=False)
        assert ui_worker.queue_state(queue) == ("No tasks", "grey")

    def test_failures_degrade_then_fail(self) -> None:
        # The health check's thresholds: one rule for every view.
        assert (
            ui_worker.queue_state(_queue("q", failure_rate_percent=15))[0] == "Degraded"
        )
        assert (
            ui_worker.queue_state(_queue("q", failure_rate_percent=30))[0] == "Failing"
        )

    def test_a_backed_up_queue_says_so_and_why(self) -> None:
        queue = _queue(
            "q", queued_jobs=40, oldest_waiting_seconds=720, max_wait_seconds=300
        )
        assert ui_worker.queue_state(queue) == ("Backed up", "yellow")
        assert "12m" in ui_worker.queue_view(queue)["detail"]

    def test_a_healthy_queue_has_no_detail(self) -> None:
        assert ui_worker.queue_view(_queue("q"))["detail"] == ""

    def test_busy_then_idle(self) -> None:
        assert ui_worker.queue_state(_queue("q", jobs_ongoing=2)) == (
            "Active",
            "yellow",
        )
        assert ui_worker.queue_state(_queue("q")) == ("Online", "green")


class TestFullness:
    def test_slots_are_concurrency_times_consumers(self) -> None:
        view = ui_worker.queue_view(_queue("q", jobs_ongoing=3, consumer_count=2))
        assert view["slots"] == 20
        assert view["busy"] == 3
        assert view["busy_pct"] == 15

    def test_an_offline_queue_still_shows_its_configured_slots(self) -> None:
        view = ui_worker.queue_view(_queue("q", worker_alive=False, consumer_count=0))
        assert view["slots"] == 10 and view["busy_pct"] == 0

    def test_busy_is_capped_at_full(self) -> None:
        """Stale "running" records can outnumber the slots; full is full."""
        assert ui_worker.queue_view(_queue("q", jobs_ongoing=40))["busy_pct"] == 100

    def test_success_rate_needs_history(self) -> None:
        assert ui_worker.queue_view(_queue("q"))["success"] is None
        done = ui_worker.queue_view(_queue("q", jobs_completed=99, jobs_failed=1))
        assert done["success"] == 99.0 and done["success_color"] == "green"


class TestOverview:
    def test_totals_and_each_queues_share(self) -> None:
        view = ui_worker.overview(
            _worker(
                _queue("system", queued_jobs=30, jobs_ongoing=2, jobs_completed=90),
                _queue("load_test", queued_jobs=10, jobs_completed=10, jobs_failed=10),
            )
        )
        assert view["queued"] == 40
        assert view["busy"] == 2 and view["slots"] == 20 and view["busy_pct"] == 10
        shares = {q["name"]: q["backlog_share"] for q in view["queues"]}
        assert shares == {"system": 75, "load_test": 25}
        work = {q["name"]: q["work_share"] for q in view["queues"]}
        assert work == {"system": 82, "load_test": 18}  # of 110 finished
        assert view["success"] == round(100 * 100 / 110, 1)

    def test_no_queues_is_an_empty_overview(self) -> None:
        view = ui_worker.overview(ComponentStatus(name="worker", message=""))
        assert view["queues"] == [] and view["busy_pct"] == 0


class TestTaskStatus:
    def test_every_status_has_a_label_and_colour(self) -> None:
        assert ui_worker.task_status("failed") == ("Failed", "red")
        assert ui_worker.task_status("mystery") == ("Mystery", "grey")


class TestPile:
    """Waiting jobs as blocks: one per job while they fit, then shared."""

    def test_a_block_per_job_while_they_fit(self) -> None:
        assert ui_worker.pile(7, cells=40) == {"lit": 7, "per_block": 1}

    def test_blocks_stand_for_more_jobs_past_the_cap(self) -> None:
        assert ui_worker.pile(342, cells=40) == {"lit": 38, "per_block": 9}

    def test_nothing_waiting_lights_nothing(self) -> None:
        assert ui_worker.pile(0, cells=40) == {"lit": 0, "per_block": 1}


class TestTrend:
    """Rate, drain time and the waiting line, from samples the live stream
    keeps: (seconds, waiting, done)."""

    def test_rate_is_jobs_done_per_second_over_the_window(self) -> None:
        samples = [(0.0, 300, 100), (10.0, 280, 124), (20.0, 250, 148)]
        assert ui_worker.rate(samples) == 2.4

    def test_rate_needs_enough_time_between_samples(self) -> None:
        assert ui_worker.rate([(0.0, 5, 1), (0.5, 4, 2)]) is None

    def test_net_rate_is_how_fast_the_backlog_shrinks(self) -> None:
        """Finishing minus arriving: the change in waiting over the window."""
        samples = [(0.0, 300, 100), (10.0, 280, 124), (20.0, 250, 148)]
        assert ui_worker.net_rate(samples) == 2.5
        assert ui_worker.net_rate([(0.0, 20, 0), (10.0, 30, 26)]) == -1.0
        assert ui_worker.net_rate([(0.0, 5, 1), (0.5, 4, 2)]) is None

    def test_drain_forecast_uses_the_net_rate(self) -> None:
        assert ui_worker.drain(250, 2.4, net=2.5) == "drains in ~2 min"
        assert ui_worker.drain(20, 2.0, net=2.0) == "drains in ~10s"
        assert ui_worker.drain(0, 2.0, net=0.0) == "caught up"
        assert ui_worker.drain(50, None, net=None) == "measuring"

    def test_arrivals_keeping_pace_is_steady_not_draining(self) -> None:
        """Jobs arriving about as fast as they finish: it never drains."""
        assert ui_worker.drain(22, 2.6, net=0.1) == "steady, keeping pace"

    def test_arrivals_outpacing_the_workers_is_growing(self) -> None:
        assert ui_worker.drain(90, 2.4, net=-1.5) == "growing by ~1.5 jobs/s"

    def test_nothing_finishing_is_stalled(self) -> None:
        assert ui_worker.drain(50, 0.0, net=0.0) == "stalled, nothing finishing"

    def test_the_waiting_line_spans_the_box(self) -> None:
        points = ui_worker.sparkline([0, 10, 5], width=100, height=20)
        assert points == "0.0,20.0 50.0,0.0 100.0,10.0"

    def test_a_flat_or_single_line_sits_on_the_floor(self) -> None:
        assert (
            ui_worker.sparkline([0, 0], width=100, height=20) == "0.0,20.0 100.0,20.0"
        )
        assert ui_worker.sparkline([], width=100, height=20) == ""

    def test_a_steady_line_draws_the_same_however_long(self) -> None:
        """An idle or steady queue must not change the page every sample."""
        assert (
            ui_worker.sparkline([0] * 3, width=100, height=20) == "0.0,20.0 100.0,20.0"
        )
        assert ui_worker.sparkline([7] * 2, width=100, height=20) == (
            ui_worker.sparkline([7] * 50, width=100, height=20)
        )


class TestHeldCapacity:
    """What the workers report holding beats the configured limit."""

    def test_reported_capacity_replaces_the_configured_one(self) -> None:
        view = ui_worker.overview(_worker(_queue("q", jobs_ongoing=5)), held={"q": 100})
        assert view["queues"][0]["slots"] == 100
        assert view["queues"][0]["busy_pct"] == 5
        assert view["slots"] == 100

    def test_without_a_report_the_configured_limit_stands(self) -> None:
        assert ui_worker.overview(_worker(_queue("q")), held={})["slots"] == 10


class TestQueuesSampler:
    """The queues are a sampler (``app.core.series``): one health check a
    tick for every viewer, each queue's waiting and finished counts kept as
    series so a reconnecting view keeps its trend."""

    async def test_a_reading_is_the_worker_and_each_queues_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worker = _worker(
            _queue("system", queued_jobs=30, jobs_completed=90, jobs_failed=2)
        )

        async def checked() -> ComponentStatus:
            return worker

        async def reports() -> list[dict[str, str]]:
            return [{"queue": "system", "concurrency": "4"}]

        monkeypatch.setattr(ui_worker, "load_worker", checked)
        monkeypatch.setattr(ui_worker, "load_runtime", reports)
        sample = await ui_worker.read_queues()
        assert sample.values == {"system:queued": 30, "system:done": 92}
        assert sample.latest == (worker, [{"queue": "system", "concurrency": "4"}])

    def test_kept_series_become_the_trends_samples(self) -> None:
        found = {
            "system:queued": [(0.0, 300.0), (10.0, 276.0)],
            "system:done": [(0.0, 100.0), (10.0, 124.0)],
        }
        assert ui_worker.samples(found, "system") == [(0.0, 300, 100), (10.0, 276, 124)]
        assert ui_worker.samples(found, "other") == []
