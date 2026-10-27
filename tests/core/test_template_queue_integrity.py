"""Every queue module the template ships is a queue something serves.

The template once shipped ``app/components/worker/queues/media.py``: a full
arq ``WorkerSettings`` with an empty ``functions`` list, its real tasks
commented out, and no ``worker-media`` service in the compose file. It read
as a shipped feature, appeared in ``aegis init``'s queue listing, and
collided with the media plugin's own ``media`` queue.

A queue module is only real when it declares tasks *and* a container runs
it. This test guards both halves, so the stub cannot come back as either
half alone.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from aegis.core.component_files import get_template_path
from tests.core import _compose

QUEUES_DIR = "app/components/worker/queues"

# Only arq queue modules are named ``<queue>.py``; the other engines append
# their own suffix (``system_taskiq.py``), so they are the same queue.
OTHER_ENGINES = ("_dramatiq.py", "_taskiq.py")


def template_queue_modules() -> list[Path]:
    """The template's arq queue modules, one per queue name."""
    root = get_template_path() / "{{ project_slug }}" / QUEUES_DIR
    return sorted(
        path
        for path in root.glob("*.py")
        if path.name != "__init__.py" and not path.name.endswith(OTHER_ENGINES)
    )


def worker_functions(module: Path) -> list[ast.expr] | None:
    """The ``functions`` list assigned in ``WorkerSettings``, if any."""
    tree = ast.parse(module.read_text())
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "WorkerSettings":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if "functions" in targets and isinstance(stmt.value, ast.List):
                return stmt.value.elts
    return None


def test_template_ships_the_queues_it_claims() -> None:
    """The stack's own queues are discovered by globbing this directory."""
    assert {module.stem for module in template_queue_modules()} >= {
        "system",
        "load_test",
    }


@pytest.mark.parametrize("module", template_queue_modules(), ids=lambda path: path.stem)
def test_queue_module_declares_tasks(module: Path) -> None:
    """An empty ``functions`` list is a queue nothing can ever run."""
    functions = worker_functions(module)
    assert functions, (
        f"{module.name} declares no tasks. A queue module with an empty "
        "``functions`` list advertises a feature no worker serves; delete "
        "it, or give it its tasks and a worker container."
    )


def test_every_template_queue_has_a_worker_container() -> None:
    """A queue without a container in the compose file is dead config.

    Rendered with every queue-owning component on: the meetings service
    ships its own queue module and its own worker, so the fullest stack is
    the one where all template queue modules are present at once.
    """
    compose = _compose.render(
        "docker-compose.yml.jinja", include_worker=True, include_meetings=True
    )
    services = yaml.safe_load(compose)["services"]
    missing = [
        f"worker-{module.stem.replace('_', '-')}"
        for module in template_queue_modules()
        if f"worker-{module.stem.replace('_', '-')}" not in services
    ]
    assert not missing, (
        f"{', '.join(missing)} declared as queue(s) but no service runs them. "
        "``docker-compose.yml.jinja`` renders ``worker-<queue>`` for plugin "
        "queues only, so a queue the template ships needs its own service."
    )
