"""Waiting for a background job to land, without guessing at iterations.

The runner's task only advances while the test client is inside a request,
so a test drives the job by asking about it. A fixed number of asks is a
bet on how fast the machine is; CI took that bet and lost.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

TIMEOUT_SECONDS = 20.0
POLL_SECONDS = 0.02


def wait_for_job(
    client: TestClient, job_id: str, *, timeout: float = TIMEOUT_SECONDS
) -> dict[str, Any]:
    """The job's snapshot once it stops running, or its last one at timeout."""
    deadline = time.monotonic() + timeout
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body.get("status") != "running":
            return body
        time.sleep(POLL_SECONDS)
    return body
