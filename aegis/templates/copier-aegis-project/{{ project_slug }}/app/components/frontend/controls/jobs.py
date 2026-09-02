"""Following a server job from the dashboard.

An endpoint called with ``background=true`` answers ``{"job_id": ...}``;
``follow_job`` reads that job's SSE stream until it lands, handing each
label to the caller as it arrives. The page-wide overlay and the
documents pane both sit on this; neither knows whether the job ran in the
webserver or on a worker.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
import json
from typing import Any

# SSE streams stay open for the job's whole life; a long extraction is
# minutes, not the client's ten-second default.
SSE_TIMEOUT = 600.0


@dataclass
class JobOutcome:
    result: dict[str, Any] | None = None
    error: str | None = None


async def _snapshots(api: Any, endpoint: str) -> AsyncIterator[dict[str, Any]]:
    """Job snapshots off an SSE endpoint, until the server closes it.

    Raises on a non-200 so callers can say so; a dropped connection
    surfaces the same way.
    """
    async with api.stream("GET", endpoint, timeout=SSE_TIMEOUT) as response:
        if response.status_code != 200:
            raise RuntimeError(
                f"Could not follow the job (HTTP {response.status_code})."
            )
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                yield json.loads(line[len("data:") :])


async def follow_job(
    api: Any, job_id: str, *, on_label: Callable[[str], None]
) -> JobOutcome:
    """Read one job's status stream to its end; never raises."""
    try:
        async for snapshot in _snapshots(api, f"/api/v1/jobs/{job_id}/events"):
            status = snapshot.get("status")
            if status == "running":
                if snapshot.get("label"):
                    on_label(str(snapshot["label"]))
                continue
            if status == "done":
                return JobOutcome(result=snapshot.get("result") or {})
            return JobOutcome(error=snapshot.get("error") or "The operation failed.")
    except Exception as e:  # noqa: BLE001 - the caller shows this, not a traceback
        return JobOutcome(error=str(e) or "Lost the job stream.")
    return JobOutcome(error="The job stream ended without a result.")


async def follow_jobs(
    api: Any, *, on_snapshot: Callable[[dict[str, Any]], None]
) -> None:
    """Hand every job's status change to ``on_snapshot`` until the stream
    ends. The live feed behind an activity view; never raises."""
    try:
        async for snapshot in _snapshots(api, "/api/v1/jobs/events"):
            on_snapshot(snapshot)
    except Exception:  # noqa: BLE001 - a lost feed is not the view's problem
        return
