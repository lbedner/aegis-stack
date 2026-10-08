"""The Server page's Load Tests: start a run against one of this app's own
routes, watch it over SSE, and see the recent ones, the CLI's included."""

import asyncio
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_server_load_tests as load_tests
from app.services.load_test.api import auth
from app.services.load_test.api.discovery import describe_routes
from tests.web import test_overseer_server as server_page
from tests.web.dom import none, one, select, text, triggers
from tests.web.overseer import sent_events

# The Server page's own sign-in and fetch: this is one of its sections.
signed_in = server_page.signed_in
_get = server_page._get


class FakeRunner:
    """The job runner's ``start`` and ``get``: no ``list_all``, which scans
    the shared store for every job anyone started."""

    def __init__(self) -> None:
        self.started: list[tuple[str, Any]] = []
        self.jobs: dict[str, Any] = {}

    def start(self, name: str, work: Any, *, label: str = "") -> str:
        self.started.append((name, work))
        return f"job-{len(self.started)}"

    def get(self, job_id: str) -> Any:
        return self.jobs.get(job_id)


class FakeHandle:
    def __init__(self) -> None:
        self.labels: list[str] = []

    def set_label(self, label: str) -> None:
        self.labels.append(label)


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(load_tests, "get_job_runner", lambda: fake)
    monkeypatch.setattr(auth, "auth_installed", lambda: False)  # no users to make
    return fake


def _target(client: TestClient) -> str:
    """A GET route of the app with no path params."""
    routes = describe_routes(client.app.routes)  # type: ignore[attr-defined]
    return next(
        f"GET {r.path}" for r in routes if r.method == "GET" and not r.path_params
    )


def _form(client: TestClient, **fields: str) -> dict[str, str]:
    return {"route": _target(client), "requests": "20", "clients": "2"} | fields


class TestStarting:
    def test_the_form_offers_the_apps_routes_not_overseers(
        self, signed_in: TestClient
    ) -> None:
        options = [
            text(o)
            for o in select(_get(signed_in, "load-tests"), "select[name=route] option")
        ]
        assert _target(signed_in) in options
        assert not [o for o in options if " /overseer" in o or " /partials" in o]

    def test_a_run_is_started_as_a_job_through_the_clis_service(
        self, signed_in: TestClient, runner: FakeRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def run(config: Any, app: Any, progress: Any) -> Any:
            seen["config"] = config
            for done in range(1, 21):
                progress(done, 20)

            class Result:
                test_id = "htl_1"

            return Result()

        monkeypatch.setattr(load_tests, "run_and_store", run)
        response = signed_in.post(load_tests.PARTIALS, data=_form(signed_in))

        assert triggers(response)["toast"]["tone"] == "ok"
        name, work = runner.started[0]
        assert name == f"{load_tests.JOB_PREFIX}{_target(signed_in)}"
        handle = FakeHandle()
        assert asyncio.run(work(handle)) == {"test_id": "htl_1"}
        assert seen["config"].in_process and seen["config"].requests == 20
        assert handle.labels[-1] == "20 of 20 requests"

    @pytest.mark.parametrize(
        "fields, why",
        [
            ({"route": "GET /overseer"}, "this app's routes"),
            ({"requests": str(load_tests.MAX_REQUESTS + 1)}, "the CLI takes more"),
            ({"clients": "0"}, "the CLI takes more"),
            ({"body": "{not json"}, "not JSON"),
        ],
    )
    def test_a_run_out_of_bounds_is_refused(
        self,
        signed_in: TestClient,
        runner: FakeRunner,
        fields: dict[str, str],
        why: str,
    ) -> None:
        response = signed_in.post(load_tests.PARTIALS, data=_form(signed_in, **fields))

        toast = triggers(response)["toast"]
        assert toast["tone"] == "error" and why in toast["text"]
        assert runner.started == []


class TestWatching:
    @pytest.mark.asyncio
    async def test_the_running_list_reads_only_the_jobs_started_here(
        self, runner: FakeRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.system.jobs import JobSnapshot

        name = f"{load_tests.JOB_PREFIX}GET /health/"
        job_id = runner.start(name, None)
        load_tests.started_jobs.add(job_id)
        runner.jobs[job_id] = JobSnapshot(job_id, name, "running", "1 of 2", None, None)

        jobs = await load_tests.load_jobs()

        assert [j.label for j in jobs] == ["1 of 2"]
        runner.jobs[job_id] = JobSnapshot(job_id, name, "done", "", {}, None)
        assert await load_tests.load_jobs() == []
        assert job_id not in load_tests.started_jobs  # done: forgotten

    def test_a_running_job_shows_its_progress(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.system.jobs import JobSnapshot

        async def jobs() -> list[JobSnapshot]:
            name = f"{load_tests.JOB_PREFIX}GET /health/"
            return [
                JobSnapshot("j1", name, "running", "40 of 100 requests", None, None)
            ]

        monkeypatch.setattr(load_tests, "load_jobs", jobs)
        job = one(_get(signed_in, "load-tests"), "#server-load-tests [data-job]")
        assert "GET /health/" in text(job) and "40 of 100 requests" in text(job)

    def test_the_runs_stream_themselves(self, signed_in: TestClient) -> None:
        live = one(_get(signed_in, "load-tests"), "#server-load-tests-live")
        assert live.get("sse-connect") == load_tests.EVENTS
        assert one(live, "[sse-swap]").get("sse-swap") == load_tests.EVENT

    def test_a_run_that_only_redirected_says_so(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def runs(limit: int) -> list[dict[str, Any]]:
            metrics = {"status_codes": {"307": 100}, "only_redirects": True}
            return [
                {
                    "test_id": "t1",
                    "configuration": {"path": "/health"},
                    "metrics": metrics,
                }
            ]

        monkeypatch.setattr(load_tests, "recent_runs", runs)
        one(_get(signed_in, "load-tests"), "tr[data-detail] [data-redirected]")

    def test_a_run_that_reached_its_route_does_not(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def runs(limit: int) -> list[dict[str, Any]]:
            metrics = {"status_codes": {"200": 99, "307": 1}, "only_redirects": False}
            return [
                {
                    "test_id": "t1",
                    "configuration": {"path": "/health/"},
                    "metrics": metrics,
                }
            ]

        monkeypatch.setattr(load_tests, "recent_runs", runs)
        none(_get(signed_in, "load-tests"), "[data-redirected]")

    @pytest.mark.asyncio
    async def test_the_stream_sends_the_runs_only_when_they_change(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def runs(limit: int) -> list[dict[str, Any]]:
            return []

        async def jobs() -> list[Any]:
            return []

        monkeypatch.setattr(load_tests, "recent_runs", runs)
        monkeypatch.setattr(load_tests, "load_jobs", jobs)
        monkeypatch.setattr(load_tests, "INTERVAL_SECONDS", 0)
        events = await sent_events(load_tests.events(max_frames=3))
        assert len(events) == 1 and events[0].startswith(f"event: {load_tests.EVENT}\n")


class TestLoadTests:
    def test_lists_recent_runs(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def runs(limit: int) -> list[dict[str, Any]]:
            return [
                {
                    "test_id": "t1",
                    "configuration": {"method": "GET", "path": "/health"},
                    "metrics": {
                        "overall_throughput": 250.0,
                        "latency_ms_p95": 4.2,
                        "latency_ms_max": 12.0,
                        "status_codes": {"200": 98, "500": 2},
                        "errors": [
                            {
                                "request_index": i,
                                "error_type": "HTTP500",
                                "message": "boom",
                            }
                            for i in range(7)
                        ],
                    },
                }
            ]

        monkeypatch.setattr(load_tests, "recent_runs", runs)
        html = _get(signed_in, "load-tests")
        assert (
            text(one(html, "tbody tr:not([data-detail])").cssselect("td")[2])
            == "/health"
        )
        detail = text(one(html, "tr[data-detail]"))
        assert "200: 98, 500: 2" in detail
        assert "12.0" in detail
        assert "Error samples (7)" in detail
        assert detail.count("HTTP500") == 5
        assert "and 2 more" in detail

    def test_store_failure_renders_a_notice(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(limit: int) -> list[dict[str, Any]]:
            raise ConnectionError("redis down")

        monkeypatch.setattr(load_tests, "recent_runs", broken)
        one(_get(signed_in, "load-tests"), "[data-empty]")
