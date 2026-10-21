"""A run's log on the Overseer: the lines so far, then the rest as they
are written while the run is on, under whichever row started the run."""

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_runs
from app.core import run_log
from tests.web.dom import none, one, text
from tests.web.overseer import sent_events, sign_in, status_with


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with())
    with TestClient(app) as client:
        yield client


class TestRunLog:
    def test_a_run_still_on_follows_the_rest(
        self, signed_in: TestClient, run_log_sink: run_log.MemorySink
    ) -> None:
        run_log_sink.append("r1", "a")
        run_log_sink.append("r1", "b")

        response = signed_in.get("/partials/overseer/runs/r1/log?live=1")

        assert response.status_code == 200
        box = one(response.text, "[data-run-log]")
        assert box.get("sse-connect") == "/partials/overseer/runs/r1/log/events"
        assert one(box, "pre").get("sse-swap") == "run-log"
        assert text(one(box, "pre")) == "a b"

    def test_a_finished_run_holds_no_stream(
        self, signed_in: TestClient, run_log_sink: run_log.MemorySink
    ) -> None:
        run_log_sink.append("r1", "a")
        box = one(signed_in.get("/partials/overseer/runs/r1/log").text, "[data-run-log]")
        assert box.get("sse-connect") is None
        assert one(box, "pre").get("sse-swap") is None
        assert text(box) == "Log a"

    def test_nothing_logged_yet_says_so(
        self, signed_in: TestClient, run_log_sink: run_log.MemorySink
    ) -> None:
        html = signed_in.get("/partials/overseer/runs/none/log").text
        assert "Nothing logged yet" in text(one(html, "[data-run-log]"))
        none(html, "[sse-connect]")

    def test_an_unreachable_store_is_a_503(
        self, signed_in: TestClient, run_log_sink: run_log.MemorySink, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def down(run_id: str, start: int = 0) -> list[str]:
            raise OSError("run log store unreachable")

        monkeypatch.setattr(run_log_sink, "read", down)
        assert signed_in.get("/partials/overseer/runs/r1/log").status_code == 503

    @pytest.mark.asyncio
    async def test_the_stream_sends_the_lines_only_when_more_were_written(
        self, monkeypatch: pytest.MonkeyPatch, run_log_sink: run_log.MemorySink
    ) -> None:
        monkeypatch.setattr(overseer_runs, "INTERVAL_SECONDS", 0)
        run_log_sink.append("r1", "a")
        reads: list[str] = []
        read = run_log_sink.read
        monkeypatch.setattr(
            run_log_sink, "read", lambda run_id, start=0: reads.append(run_id) or read(run_id, start)
        )

        events = await sent_events(overseer_runs.events("r1", max_frames=3))

        assert len(events) == 1 and events[0].startswith("event: run-log\n")
        assert "data: a" in events[0]
        assert reads == ["r1"], "the lines were read once, not on every tick"
