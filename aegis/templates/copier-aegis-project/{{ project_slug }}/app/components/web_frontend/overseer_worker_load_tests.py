"""The Worker page's Load tests: start a run, watch it, see the recent ones.

The same runs the CLI and the API start (``LoadTestService``): this process
sends the tasks and they are counted from task history, so a run started
anywhere shows here. The list streams over SSE while the page is open.

Worker modules are imported when called: this module ships with Overseer,
which a stack without a worker has too.
"""

from typing import Any

from pydantic import ValidationError

from app.core.formatting import format_relative_time

from .overseer_live import fragment_events
from .rendering import fragment, status_cell

EVENTS = "/overseer/events/worker-load-tests"
EVENT = "worker-load-tests"
PARTIALS = "/partials/overseer/worker"
TEMPLATE = "pages/overseer/worker/_load_test_runs.html"
INTERVAL_SECONDS = 2.0
RECENT = 20


async def load_runs() -> list[dict[str, Any]]:
    """The newest runs' counts, newest first."""
    from app.services.load_test.worker.service import LoadTestService

    return await LoadTestService.recent(RECENT)


def load_queues() -> list[str]:
    """The queues this stack runs, for the form."""
    from app.components.worker.registry import discover_worker_queues

    return discover_worker_queues()


async def begin(config: Any) -> str:
    """Start ``config``'s run, sent in the background; its test id.
    ``ValueError`` says why not (the cap, an unknown queue)."""
    from app.services.load_test.worker.service import LoadTestService

    return await LoadTestService.begin_load_test(config)


def _state(run: dict[str, Any]) -> dict[str, str]:
    if run.get("sending"):
        return status_cell("Sending", "accent")
    if not run.get("finished"):
        return status_cell("Running", "warn")
    return status_cell("Failures", "error") if run.get("tasks_failed") else status_cell("Done", "ok")


def run_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One table row per run."""
    return [
        {
            "test_id": run["test_id"],
            "type": run["task_type"].replace("_", " "),
            "queue": run["target_queue"],
            "done": f"{run['tasks_completed'] + run['tasks_failed']:,} / {run['tasks_planned']:,}",
            "failed": f"{run['tasks_failed']:,}",
            "duration": f"{run['total_duration_seconds']:.1f}s",
            "rate": f"{run['overall_throughput_per_second']:.1f}/s",
            "state": _state(run),
            "when": format_relative_time(run["start_time"]),
        }
        for run in runs
    ]


async def _render() -> str:
    return fragment(TEMPLATE, runs=run_rows(await load_runs()))


def events(max_frames: int | None = None):  # noqa: ANN201 - async iterator
    """The runs over SSE, sent again only when they change."""
    return fragment_events(EVENT, _render, INTERVAL_SECONDS, max_frames)


async def section_context() -> dict[str, Any]:
    """The form's choices and the runs as they stand."""
    from app.components.worker.constants import LoadTestTypes
    from app.services.load_test.worker.service import MAX_BACKGROUND_TASKS

    return {
        "runs": run_rows(await load_runs()),
        "events": EVENTS,
        "event": EVENT,
        "partials": PARTIALS,
        "types": [{"id": t.value, "name": t.value.replace("_", " ")} for t in LoadTestTypes],
        "queues": [{"id": q, "name": q} for q in load_queues()],
        "max_tasks": MAX_BACKGROUND_TASKS,
    }


async def start(form: dict[str, str]) -> tuple[str | None, str]:
    """Start a run from the form: its test id, or None and why not."""
    from app.services.load_test.worker.models import LoadTestConfiguration

    try:
        config = LoadTestConfiguration.model_validate(form)
    except ValidationError as exc:
        return None, "; ".join(e["msg"] for e in exc.errors())
    try:
        return await begin(config), ""
    except ValueError as exc:
        return None, str(exc)
