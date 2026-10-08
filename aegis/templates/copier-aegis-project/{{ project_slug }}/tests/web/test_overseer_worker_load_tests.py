"""The Worker page's Load tests: start a run, watch it over SSE, see the
recent ones. The same runs the CLI and the API start."""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_worker_load_tests as load_tests
from app.services.system import ui_worker
from app.services.system.models import ComponentStatus
from tests._fake_runtime import queue_status, worker_status
from tests.web.dom import one, select, text, triggers
from tests.web.overseer import page_html, sent_events, sign_in, status_with

WORKER = worker_status(queue_status("load_test"), message="TaskIQ worker")
PAGE = "/overseer/components/worker/load-tests"
FORM = {
    "task_type": "io_simulation",
    "num_tasks": "50",
    "batch_size": "10",
    "delay_ms": "0",
    "target_queue": "load_test",
}

RUN = {
    "test_id": "wlt_20261008T101500_abc123",
    "task_type": "io_simulation",
    "tasks_planned": 3,
    "tasks_sent": 3,
    "tasks_completed": 1,
    "tasks_failed": 1,
    "target_queue": "load_test",
    "start_time": "2026-10-08T10:15:00+00:00",
    "total_duration_seconds": 4.0,
    "overall_throughput_per_second": 0.25,
    "sending": False,
    "finished": False,
}


@pytest.fixture
def started() -> list[Any]:
    return []


@pytest.fixture
def signed_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, started: list[Any]
) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(WORKER))

    async def worker() -> ComponentStatus:
        return WORKER

    async def runs() -> list[dict[str, Any]]:
        return [RUN]

    async def begin(config: Any) -> str:
        started.append(config)
        return "wlt_new"

    monkeypatch.setattr(ui_worker, "load_worker", worker)
    monkeypatch.setattr(load_tests, "load_runs", runs)
    monkeypatch.setattr(load_tests, "load_queues", lambda: ["load_test", "system"])
    monkeypatch.setattr(load_tests, "begin", begin)
    with TestClient(app) as client:
        yield client


def test_a_run_shows_its_progress_and_state(signed_in: TestClient) -> None:
    row = select(page_html(signed_in, PAGE), "#worker-load-tests tbody tr")[0]
    assert RUN["test_id"] in text(row)
    assert "2 / 3" in text(row)  # finished, failed included, of planned
    assert one(row, "[data-tone]").get("data-tone") == "warn"  # running


def test_the_runs_stream_themselves(signed_in: TestClient) -> None:
    live = one(page_html(signed_in, PAGE), "#worker-load-tests-live")
    assert live.get("sse-connect") == load_tests.EVENTS
    assert one(live, "[sse-swap]").get("sse-swap") == load_tests.EVENT


def test_a_run_is_started_from_the_form(
    signed_in: TestClient, started: list[Any]
) -> None:
    response = signed_in.post(f"{load_tests.PARTIALS}/load-tests", data=FORM)

    assert triggers(response)["toast"]["tone"] == "ok"
    assert "wlt_new" in triggers(response)["toast"]["text"]
    assert started[0].num_tasks == 50 and started[0].target_queue == "load_test"


def test_a_form_that_does_not_parse_is_refused(
    signed_in: TestClient, started: list[Any]
) -> None:
    response = signed_in.post(
        f"{load_tests.PARTIALS}/load-tests", data=FORM | {"num_tasks": "0"}
    )

    assert triggers(response)["toast"]["tone"] == "error"
    assert started == []


def test_the_services_refusal_is_the_toast(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(config: Any) -> str:
        raise ValueError("At most 10,000 tasks from here")

    monkeypatch.setattr(load_tests, "begin", refuse)
    response = signed_in.post(f"{load_tests.PARTIALS}/load-tests", data=FORM)

    toast = triggers(response)["toast"]
    assert toast["tone"] == "error" and "10,000" in toast["text"]


@pytest.mark.asyncio
async def test_the_stream_sends_the_runs_only_when_they_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def runs() -> list[dict[str, Any]]:
        return [RUN]

    monkeypatch.setattr(load_tests, "load_runs", runs)
    monkeypatch.setattr(load_tests, "INTERVAL_SECONDS", 0)
    events = await sent_events(load_tests.events(max_frames=3))
    assert len(events) == 1
    assert events[0].startswith(f"event: {load_tests.EVENT}\n")
