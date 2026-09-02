"""Following a server job's SSE stream, minus the server."""

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any

from app.components.frontend.controls.jobs import follow_job, follow_jobs


class _Response:
    def __init__(self, status: int, frames: list[dict[str, Any]]) -> None:
        self.status_code = status
        self._frames = frames

    async def aiter_lines(self):
        for frame in self._frames:
            yield "event: status"
            yield f"data: {json.dumps(frame)}"
            yield ""


class _Api:
    def __init__(self, status: int, frames: list[dict[str, Any]]) -> None:
        self._response = _Response(status, frames)

    @asynccontextmanager
    async def stream(self, method: str, endpoint: str, timeout: float | None = None):
        yield self._response


def test_labels_are_reported_and_the_result_returned() -> None:
    labels: list[str] = []
    api = _Api(
        200,
        [
            {"status": "running", "label": "page 1 of 2"},
            {"status": "running", "label": "page 2 of 2"},
            {"status": "done", "result": {"read": 2}},
        ],
    )

    outcome = asyncio.run(follow_job(api, "j1", on_label=labels.append))

    assert labels == ["page 1 of 2", "page 2 of 2"]
    assert outcome.result == {"read": 2} and outcome.error is None


def test_a_failed_job_carries_its_error() -> None:
    api = _Api(200, [{"status": "failed", "error": "model not found"}])

    outcome = asyncio.run(follow_job(api, "j1", on_label=lambda _l: None))

    assert outcome.result is None and outcome.error == "model not found"


def test_a_bad_stream_status_is_an_error_not_a_hang() -> None:
    api = _Api(404, [])

    outcome = asyncio.run(follow_job(api, "j1", on_label=lambda _l: None))

    assert outcome.result is None and "404" in (outcome.error or "")


def test_following_every_job_hands_each_snapshot_over() -> None:
    seen: list[dict[str, Any]] = []
    api = _Api(
        200,
        [
            {"job_id": "a", "status": "running", "label": "page 1"},
            {"job_id": "b", "status": "done", "result": {"read": 2}},
        ],
    )

    asyncio.run(follow_jobs(api, on_snapshot=seen.append))

    assert [s["job_id"] for s in seen] == ["a", "b"]
