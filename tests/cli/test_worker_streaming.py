"""
Tests for streaming worker event infrastructure.

Verifies that generated projects with the worker component contain
the correct SSE event streaming files, middleware wiring, and
frontend listener code.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.cli.conftest import ProjectFactory


class TestWorkerEventInfrastructure:
    """Verify event streaming files exist and contain correct code."""

    def test_worker_project_has_events_module(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Worker projects should have events.py for Redis Stream publishing."""
        project_path = project_factory("base_with_worker")
        events_file = project_path / "app" / "components" / "worker" / "events.py"
        assert events_file.exists()

    def test_taskiq_project_has_middleware(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """TaskIQ worker projects should have middleware.py (renamed from middleware_taskiq.py)."""
        project_path = project_factory("base_with_worker_taskiq")
        middleware_file = (
            project_path / "app" / "components" / "worker" / "middleware.py"
        )
        assert middleware_file.exists()

    def test_arq_project_no_middleware_file(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """arq worker projects should NOT have any middleware file (arq uses queue hooks)."""
        project_path = project_factory("base_with_worker")
        worker_dir = project_path / "app" / "components" / "worker"
        assert not (worker_dir / "middleware.py").exists()
        assert not (worker_dir / "middleware_taskiq.py").exists()
        assert not (worker_dir / "middleware_dramatiq.py").exists()

    def test_arq_registry_uses_worker_settings(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """arq registry.py should introspect WorkerSettings, not import from middleware."""
        project_path = project_factory("base_with_worker")
        content = (
            project_path / "app" / "components" / "worker" / "registry.py"
        ).read_text()
        assert "get_worker_settings" in content
        assert "from app.components.worker.middleware" not in content

    def test_worker_project_has_sse_endpoint(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Worker projects should have api/events.py for the SSE endpoint."""
        project_path = project_factory("base_with_worker")
        sse_file = project_path / "app" / "components" / "backend" / "api" / "events.py"
        assert sse_file.exists()


class TestEventWiring:
    """Verify event publishing and middleware are wired correctly."""

    def test_events_has_publish_and_totals(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """events.py should contain publish_event, read_queue_totals, and the stream name."""
        project_path = project_factory("base_with_worker")
        content = (
            project_path / "app" / "components" / "worker" / "events.py"
        ).read_text()
        assert "publish_event" in content
        assert "read_queue_totals" in content
        assert "WORKER_EVENT_STREAM" in content

    def test_taskiq_middleware_publishes_lifecycle_events(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """middleware.py (from TaskIQ backend) should publish all 5 lifecycle event types."""
        project_path = project_factory("base_with_worker_taskiq")
        content = (
            project_path / "app" / "components" / "worker" / "middleware.py"
        ).read_text()
        for event_type in [
            "worker.started",
            "worker.stopped",
            "job.started",
            "job.completed",
            "job.failed",
        ]:
            assert event_type in content, f"Missing event type: {event_type}"

    def test_arq_queues_publish_lifecycle_events(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """arq queue files should publish lifecycle events via on_startup/after_job_end hooks."""
        project_path = project_factory("base_with_worker")
        queues_dir = project_path / "app" / "components" / "worker" / "queues"
        for queue_name in ["system.py", "load_test.py"]:
            queue_file = queues_dir / queue_name
            assert queue_file.exists(), f"{queue_name} not found"
            content = queue_file.read_text()
            assert "publish_event" in content, f"{queue_name} missing publish_event"
            assert "on_startup" in content, f"{queue_name} missing on_startup"
            assert "after_job_end" in content, f"{queue_name} missing after_job_end"

    def test_both_queues_publish_events(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """Both system and load_test queue files should publish worker events."""
        project_path = project_factory("base_with_worker")
        queues_dir = project_path / "app" / "components" / "worker" / "queues"

        system_content = (queues_dir / "system.py").read_text()
        assert "publish_event" in system_content

        load_test_content = (queues_dir / "load_test.py").read_text()
        assert "publish_event" in load_test_content


class TestSSEEndpoint:
    """Verify the SSE endpoint structure and routing."""

    def test_sse_endpoint_structure(self, project_factory: "ProjectFactory") -> None:
        """api/events.py should contain the SSE endpoint with correct components."""
        project_path = project_factory("base_with_worker")
        content = (
            project_path / "app" / "components" / "backend" / "api" / "events.py"
        ).read_text()
        assert "worker_event_stream" in content
        assert "text/event-stream" in content
        assert "read_queue_totals" in content

    def test_sse_endpoint_in_routing(self, project_factory: "ProjectFactory") -> None:
        """routing.py should include the events router."""
        project_path = project_factory("base_with_worker")
        content = (
            project_path / "app" / "components" / "backend" / "api" / "routing.py"
        ).read_text()
        assert "worker_events" in content
        assert "events" in content


class TestFrontendSSEListener:
    """Verify the frontend SSE listener and flush logic.

    The SSE listener in main.py is gated on ``include_worker AND include_redis``,
    so these tests must generate a project with both components.
    """

    def test_frontend_sse_listener_and_flush(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """main.py should define listen_for_worker_events and flush_worker_modal."""
        project_path = project_factory(components=["worker", "redis"])
        content = (
            project_path / "app" / "components" / "frontend" / "main.py"
        ).read_text()
        assert "listen_for_worker_events" in content
        assert "flush_worker_modal" in content
        assert content.count("create_task") >= 2

    def test_frontend_dispatches_all_event_types(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """The listener should dispatch all SSE event types to the worker popup."""
        project_path = project_factory(components=["worker", "redis"])
        content = (
            project_path / "app" / "components" / "frontend" / "overseer" / "loops.py"
        ).read_text()
        for method in [
            "increment_queued",
            "increment_ongoing",
            "increment_completed",
            "increment_failed",
            "set_totals",
        ]:
            assert method in content, f"Missing dispatch method: {method}"


class TestModalCacheHandling:
    """Verify modal cache preserves worker popup during refresh."""

    def test_worker_modal_cached_permanently(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """The loops should keep the worker modal cached so SSE counters
        survive close/reopen."""
        project_path = project_factory(components=["worker", "redis"])
        frontend = project_path / "app" / "components" / "frontend"
        # Both halves: the bootstrap and the loops that read the cache.
        # Checking only ``main.py`` would pass vacuously now that the
        # cache reads live in ``overseer/loops.py``.
        for module in (frontend / "main.py", frontend / "overseer" / "loops.py"):
            # Should NOT prune the worker popup from cache on close
            assert "_cache.pop" not in module.read_text(), module.name


class TestWorkerModalSSEMethods:
    """Verify the worker modal has SSE-driven counter methods."""

    def test_worker_modal_has_sse_methods(
        self, project_factory: "ProjectFactory"
    ) -> None:
        """The worker modal should have set_totals, flush, _dirty, and all counter methods."""
        project_path = project_factory("base_with_worker")
        modal_dir = (
            project_path
            / "app"
            / "components"
            / "frontend"
            / "dashboard"
            / "modals"
            / "worker_modal"
        )
        content = "\n".join(f.read_text() for f in sorted(modal_dir.glob("*.py")))
        for method in [
            "set_totals",
            "flush",
            "_dirty",
            "increment_queued",
            "decrement_queued",
            "increment_ongoing",
            "increment_completed",
            "increment_failed",
        ]:
            assert method in content, f"Missing SSE method: {method}"


class TestBaseProjectNoWorkerEvents:
    """Verify base projects without worker don't have event streaming code."""

    def test_base_no_worker_events(self, project_factory: "ProjectFactory") -> None:
        """Base projects should not have worker event infrastructure."""
        project_path = project_factory("base")
        worker_dir = project_path / "app" / "components" / "worker"
        assert not worker_dir.exists()

        frontend = project_path / "app" / "components" / "frontend"
        # The listener is gated in both places: ``main.py`` does not import
        # it and ``overseer/loops.py`` does not define it.
        for module in (frontend / "main.py", frontend / "overseer" / "loops.py"):
            assert "listen_for_worker_events" not in module.read_text(), module.name
