"""The Server page's Load Tests: start a run against one of this app's own
routes, watch it, and see the recent ones, the CLI's included.

A run goes through the CLI's service (``APILoadTestService``) and lands in
the same store, so ``api-load-test list`` sees it too. It runs in this
process against the app itself (no network), as a background job whose
label is its progress. The section streams over SSE while it is open.
"""

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import FastAPI
from markupsafe import Markup
from pydantic import ValidationError
from starlette.routing import BaseRoute

from app.components.backend.api.load_test_api import recent_runs, run_and_store
from app.core.formatting import format_relative_time
from app.core.log import logger
from app.services.load_test.api import auth, request_form
from app.services.load_test.api.discovery import describe_routes
from app.services.load_test.api.models import APILoadTestConfiguration
from app.services.load_test.api.request_form import Operation
from app.services.system import ui_backend
from app.services.system.jobs import JobHandle, JobSnapshot, get_job_runner

from . import overseer_requests
from .overseer_live import fragment_events
from .rendering import form_number, fragment, one_decimal

EVENTS = "/overseer/events/server-load-tests"
EVENT = "server-load-tests"
PARTIALS = "/partials/overseer/server/load-tests"
TEMPLATE = "pages/overseer/server/_load_test_runs.html"
JOB_PREFIX = "api-load-test:"
INTERVAL_SECONDS = 2.0
RECENT = 50
# Started from a browser and run inside the server it measures.
MAX_REQUESTS = 5_000
MAX_CLIENTS = 50
# The runs this process started and has not seen finish. Runs start here
# and only here, so the shared job store is never scanned to find them.
started_jobs: set[str] = set()


async def load_runs() -> tuple[list[dict[str, Any]], bool]:
    """Recent runs, and whether the result store could be read."""
    try:
        return await recent_runs(limit=RECENT), True
    except Exception as exc:  # the store is optional; show why it is empty
        logger.warning("Overseer could not read load-test runs", error=str(exc))
        return [], False


async def load_jobs() -> list[JobSnapshot]:
    """Runs started here that are still going, or that failed to run; a
    finished one is forgotten (it is in the store's list now)."""
    runner = get_job_runner()
    jobs = [job for job_id in started_jobs if (job := runner.get(job_id))]
    started_jobs.difference_update(j.job_id for j in jobs if j.status == "done")
    started_jobs.intersection_update(j.job_id for j in jobs)
    return [j for j in jobs if j.status != "done"]


def run_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten each run's configuration and metrics into one table row."""
    rows = []
    for run in runs:
        row = {
            **(run.get("configuration") or {}),
            **(run.get("metrics") or {}),
            "test_id": run.get("test_id"),
            "when": format_relative_time(run.get("start_time")),
        }
        row["error_pct"] = f"{float(row.get('failure_rate_percent') or 0):.1f}%"
        row["throughput"] = f"{float(row.get('overall_throughput') or 0):.0f}"
        row["duration"] = f"{float(row.get('total_duration_seconds') or 0):.3f}s"
        ms = ("latency_ms_p50", "latency_ms_p95", "latency_ms_p99", "latency_ms_max")
        rows.append(one_decimal(row, *ms))
    return rows


async def runs_context() -> dict[str, Any]:
    """What the run list shows: the runs going now, then the recent ones."""
    runs, available = await load_runs()
    return {
        "jobs": [
            {
                "target": j.name.removeprefix(JOB_PREFIX),
                "label": j.label,
                "error": j.error,
            }
            for j in await load_jobs()
        ],
        "runs": run_rows(runs),
        "run_summary": ui_backend.load_test_summary(runs),
        "runs_available": available,
    }


async def _render() -> str:
    return fragment(TEMPLATE, **await runs_context())


def events(max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """The run list over SSE, sent again only when it changes."""
    return fragment_events(EVENT, _render, INTERVAL_SECONDS, max_frames)


async def section_context(
    routes: Sequence[BaseRoute], query: dict[str, str]
) -> dict[str, Any]:
    """The route picker, the form of the route picked (``route`` in the
    query, its values with it, as Routes' "Load test this" sends them),
    and the run list as it stands."""
    keys = [f"{r.method} {r.path}" for r in describe_routes(routes)]
    picked = query.get("route") if query.get("route") in keys else None
    picked = picked or next(iter(keys), None)
    op = overseer_requests.find(routes, picked) if picked else None
    return await runs_context() | {
        "events": EVENTS,
        "event": EVENT,
        "requests_partials": overseer_requests.PARTIALS,
        "targets": [{"id": k, "name": k} for k in keys],
        "picked": picked,
        "form_html": Markup(fragment(overseer_requests.FORM, **form_context(op, query)))
        if op
        else "",
    }


def form_context(op: Operation, values: dict[str, str]) -> dict[str, Any]:
    """Routes' request form for ``op``, with what a run adds to it."""
    return overseer_requests.form_context(op, overseer_requests.LOAD, values) | {
        "load_partials": PARTIALS,
        "requests": values.get("requests") or "100",
        "clients": values.get("clients") or "10",
        "max_requests": MAX_REQUESTS,
        "max_clients": MAX_CLIENTS,
    }


async def _config(form: dict[str, str], app: FastAPI) -> APILoadTestConfiguration:
    """The run the form asks for, checked; ``ValueError`` says what is wrong."""
    op = overseer_requests.find(app.routes, form.get("route", ""))
    if op is None:
        raise ValueError("Pick one of this app's routes.")
    requests = form_number(form.get("requests"), "Requests") or 0
    clients = form_number(form.get("clients"), "Clients") or 0
    if not 1 <= requests <= MAX_REQUESTS or not 1 <= clients <= MAX_CLIENTS:
        raise ValueError(
            f"Requests run 1 to {MAX_REQUESTS:,}, clients 1 to {MAX_CLIENTS}; "
            "the CLI takes more."
        )
    request = request_form.build(op, form)
    role = form.get("role") or auth.default_role()
    try:
        return APILoadTestConfiguration.model_validate(
            {
                "method": request.method,
                "path": request.load_test_path,
                "requests": requests,
                "clients": clients,
                "path_params": request.path_params,
                "payload": request.payload,
                "headers": await auth.bearer_header(role),
                "auth_as": None if role == auth.ANONYMOUS else role,
                "in_process": True,
            }
        )
    except ValidationError as exc:
        raise ValueError("; ".join(e["msg"] for e in exc.errors())) from None


def _progress(handle: JobHandle) -> Callable[[int, int], None]:
    """The run's progress as the job's label, about a hundred times a run."""

    def report(done: int, total: int) -> None:
        if done == total or done % max(total // 100, 1) == 0:
            handle.set_label(f"{done:,} of {total:,} requests")

    return report


async def start(form: dict[str, str], app: FastAPI) -> tuple[str | None, str]:
    """Start a run from the form: its job id, or None and why not."""
    try:
        config = await _config(form, app)
    except ValueError as exc:
        return None, str(exc)

    async def work(handle: JobHandle) -> dict[str, Any]:
        result = await run_and_store(config, app, _progress(handle))
        return {"test_id": result.test_id}

    target = f"{config.method} {config.path}"
    job_id = get_job_runner().start(f"{JOB_PREFIX}{target}", work, label="Starting")
    started_jobs.add(job_id)
    return job_id, ""
