"""What the worker views show, for Flet and the web frontend alike: each
queue's state, how full it is, and its share of the work."""

import pytest

from app.services.system import ui_worker
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests._fake_runtime import queue_status as _queue
from tests._fake_runtime import worker_status as _worker


def _state(queue: ComponentStatus) -> tuple[str, str]:
    view = ui_worker.queue_view(queue)
    return view["state"], view["color"]


class TestQueueState:
    def test_offline_without_a_consumer(self) -> None:
        assert _state(_queue("q", worker_alive=False)) == ("Offline", "red")

    def test_a_queue_with_no_tasks_is_grey(self) -> None:
        queue = _queue("q", "q: configured - no functions defined", worker_alive=False)
        assert _state(queue) == ("No tasks", "grey")
        assert ui_worker.queue_view(queue)["detail"] == ""

    def test_failures_degrade_then_fail(self) -> None:
        # The health check's thresholds: one rule for every view.
        assert _state(_queue("q", failure_rate_percent=15))[0] == "Degraded"
        assert _state(_queue("q", failure_rate_percent=30))[0] == "Failing"

    def test_a_backed_up_queue_says_so_and_why(self) -> None:
        queue = _queue(
            "q", queued_jobs=40, oldest_waiting_seconds=720, max_wait_seconds=300
        )
        assert _state(queue) == ("Backed up", "yellow")
        assert ui_worker.queue_view(queue)["detail"] == "oldest waiting 12m"

    def test_the_badge_does_not_name_its_state_twice(self) -> None:
        """The panel showed "Backed up · backed up, oldest waiting 5m 13s"
        (2026-11-07)."""
        queue = _queue(
            "q",
            queued_jobs=8,
            oldest_waiting_seconds=720,
            max_wait_seconds=300,
            last_started_seconds=400,
        )
        assert ui_worker.queue_view(queue)["detail"] == (
            "oldest waiting 12m, nothing started for 6m 40s"
        )

    def test_a_queue_still_starting_jobs_is_active_not_backed_up(self) -> None:
        queue = _queue(
            "q",
            queued_jobs=8,
            jobs_ongoing=6,
            oldest_waiting_seconds=313,
            max_wait_seconds=300,
            last_started_seconds=40,
        )
        assert _state(queue) == ("Active", "yellow")

    def test_active_reads_the_running_jobs_the_view_shows(self) -> None:
        """Task history kept five "running" records from jobs a worker
        reload dropped; the panel said Active over 0 running (2026-11-07)."""
        idle = [{"worker": "w", "slots": 6, "busy": 0}]
        view = ui_worker.queue_view(_queue("q", jobs_ongoing=5), idle)
        assert (view["busy"], view["state"]) == (0, "Online")

    def test_a_healthy_queue_has_no_detail(self) -> None:
        assert ui_worker.queue_view(_queue("q"))["detail"] == ""

    def test_busy_then_idle(self) -> None:
        assert _state(_queue("q", jobs_ongoing=2)) == (
            "Active",
            "yellow",
        )
        assert _state(_queue("q")) == ("Online", "green")


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

    def test_the_backlog_is_what_waits_and_runs(self) -> None:
        found = ui_worker.backlog(_worker(_queue("q", queued_jobs=12, jobs_ongoing=3)))
        assert found.status == ComponentStatusType.HEALTHY
        assert (found.queued, found.message) == (12, "12 queued, 3 running")

    def test_a_backlog_warns_while_a_queue_backs_up_and_says_why(self) -> None:
        backed_up = _queue(
            "q", queued_jobs=40, oldest_waiting_seconds=720, max_wait_seconds=300
        )
        found = ui_worker.backlog(_worker(backed_up))
        assert found.status == ComponentStatusType.WARNING
        assert "backed up" in found.message and "12m" in found.message

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

    def test_rate_spans_a_batch_of_slow_jobs(self) -> None:
        """Six jobs that start together finish together; a window shorter
        than one job saw none finish between batches and said "stalled"."""
        samples = [(float(t), 40, 100 + 6 * (t // 45)) for t in range(0, 121, 3)]
        assert ui_worker.rate(samples) == 0.1

    def test_a_restart_dropping_done_does_not_erase_what_finished(self) -> None:
        samples = [(0.0, 20, 910), (10.0, 18, 914), (20.0, 17, 912), (30.0, 15, 915)]
        assert ui_worker.rate(samples) == 0.23

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

    def test_a_slow_steady_drain_is_draining_not_steady(self) -> None:
        """42 waiting fell to 8 in five minutes, about 0.1 a second, and the
        panel said "steady, keeping pace" (2026-11-07)."""
        assert ui_worker.drain(8, 0.13, net=0.1) == "drains in ~1 min"

    def test_one_job_either_way_over_the_window_is_steady(self) -> None:
        """Below a job per window the net rate is one arrival's noise."""
        assert ui_worker.drain(8, 0.05, net=0.006) == "steady, keeping pace"

    def test_arrivals_outpacing_the_workers_is_growing(self) -> None:
        assert ui_worker.drain(90, 2.4, net=-1.5) == "growing by ~1.5 jobs/s"

    def test_nothing_finishing_is_stalled(self) -> None:
        assert ui_worker.drain(50, 0.0, net=0.0) == "stalled, nothing finishing"


class TestHeldCapacity:
    """What the workers report holding beats the configured limit."""

    def test_reported_capacity_replaces_the_configured_one(self) -> None:
        procs = {"q": [{"worker": "h:1", "slots": 100, "busy": 5}]}
        view = ui_worker.overview(_worker(_queue("q", jobs_ongoing=5)), procs=procs)
        assert view["queues"][0]["slots"] == 100
        assert view["queues"][0]["busy_pct"] == 5
        assert view["slots"] == 100

    def test_without_a_report_the_configured_limit_stands(self) -> None:
        assert ui_worker.overview(_worker(_queue("q")), procs={})["slots"] == 10


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
