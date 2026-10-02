"""The API models a project gets follow its worker and scheduler, nothing else.

``app/components/backend/api/models.py`` is one template with two gates:
the worker's task models (``include_worker``) and the scheduler's (any
backend but ``memory``). Worker models once sat under the scheduler's gate,
so a worker-only project had none. This renders the template for every
combination and reads the classes back; it used to run a full ``aegis
init`` per matrix stack to read the same file.
"""

from __future__ import annotations

import ast

import pytest
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path

WORKER = {
    "TaskRequest",
    "TaskResponse",
    "TaskListResponse",
    "TaskStatusResponse",
    "TaskResultResponse",
    "LoadTestRequest",
    "LoadTestStatus",
    "LoadTestResults",
}
SCHEDULER = {
    "ScheduledTaskListResponse",
    "ScheduledTaskDetailResponse",
    "JobExecutionRead",
    "TriggerJobResponse",
}


def _classes(include_worker: bool, scheduler_backend: str) -> set[str]:
    env = Environment(
        loader=FileSystemLoader(str(get_template_path())), keep_trailing_newline=True
    )
    rendered = env.get_template(
        "{{ project_slug }}/app/components/backend/api/models.py.jinja"
    ).render(
        {
            **get_copier_defaults(),
            "include_worker": include_worker,
            "scheduler_backend": scheduler_backend,
        }
    )
    tree = ast.parse(rendered)  # every combination is valid Python
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


@pytest.mark.parametrize("include_worker", [True, False])
@pytest.mark.parametrize("scheduler_backend", ["memory", "sqlite", "postgres"])
def test_each_gate_brings_exactly_its_models(
    include_worker: bool, scheduler_backend: str
) -> None:
    classes = _classes(include_worker, scheduler_backend)

    assert classes & WORKER == (WORKER if include_worker else set())
    scheduled = scheduler_backend != "memory"
    assert classes & SCHEDULER == (SCHEDULER if scheduled else set())
