"""Job status endpoints: one JSON snapshot, one SSE stream.

Long-running operations return ``202 {"job_id": ...}`` from their own
endpoints (e.g. ``POST /finance/import?background=true``); these two
endpoints are how any client follows the work. The SSE stream is the
primary path (the dashboard's LoadingOverlay consumes it); the JSON
snapshot exists for tests, curl, and anything that cannot hold a stream.

Job ids are single-use uuid4 capability tokens minted per operation, so
these endpoints carry no auth dependency of their own: knowing the id IS
the authorization, the same trust model as an unguessable download link.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.system.jobs import get_job_runner

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobStatusResponse(BaseModel):
    """Snapshot of one background job."""

    job_id: str
    name: str
    status: str  # "running" | "done" | "failed"
    label: str
    result: dict[str, Any] | None = None
    error: str | None = None


class JobStartedResponse(BaseModel):
    """What a ``?background=true`` endpoint returns with its 202."""

    job_id: str


@router.get("/{job_id}", response_model=JobStatusResponse)
async def job_status(job_id: str) -> JobStatusResponse:
    """Point-in-time job state."""
    snapshot = get_job_runner().get(job_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown job."
        )
    return JobStatusResponse(**snapshot.as_dict())


@router.get("/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    """SSE stream of job status: label updates, then one terminal event.

    Emits ``event: status`` frames whose data is the job snapshot. The
    stream closes itself after the ``done``/``failed`` frame - a client
    just reads until the terminal status (or the stream ends).
    """
    runner = get_job_runner()
    queue = runner.subscribe(job_id)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown job."
        )

    async def stream() -> AsyncIterator[str]:
        try:
            while True:
                snapshot = await queue.get()
                if snapshot is None:
                    break
                yield f"event: status\ndata: {json.dumps(snapshot)}\n\n"
                if snapshot["status"] != "running":
                    break
        except asyncio.CancelledError:
            # Client went away; nothing to clean up beyond the subscription.
            raise
        finally:
            runner.unsubscribe(job_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")
