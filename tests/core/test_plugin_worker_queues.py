"""A plugin's worker queue gets a worker.

Compose runs one worker container per queue, so a queue a plugin ships
(``app/components/worker/queues/<name>.py``) would have no process reading
it unless the plugin says so. ``PluginSpec.worker_queues`` names them, and
the stack emits ``worker-<name>`` beside its own workers: one process, so
a host paced per process stays paced, bind-mounted in dev like the rest.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path
from aegis.core.plugins.composer import PLUGINS_ANSWER_KEY, serialize_plugin_to_answer
from aegis.core.plugins.spec import PluginKind, PluginSpec

SLUG = "{{ project_slug }}"


def _render(rel: str, **answers: Any) -> str:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), **answers}
    return env.get_template(f"{SLUG}/{rel}.jinja").render(context)


def _plugin() -> dict[str, Any]:
    spec = PluginSpec(
        name="crawl4ai",
        kind=PluginKind.SERVICE,
        description="d",
        worker_queues=["crawler"],
    )
    return serialize_plugin_to_answer(spec)


def test_the_spec_has_no_queues_by_default() -> None:
    assert (
        PluginSpec(name="x", kind=PluginKind.SERVICE, description="d").worker_queues
        == []
    )


def test_the_answer_carries_the_queues() -> None:
    assert _plugin()["worker_queues"] == ["crawler"]


def test_a_worker_stack_runs_the_plugins_queue() -> None:
    compose = _render(
        "docker-compose.yml",
        include_worker=True,
        include_redis=True,
        worker_backend="taskiq",
        **{PLUGINS_ANSWER_KEY: [_plugin()]},
    )
    service = compose[compose.index("  worker-crawler:") :]
    assert "      - worker\n      - crawler\n" in service
    assert "WORKER_QUEUE_TYPE=crawler" in service
    assert "WORKER_PROCESSES=${CRAWLER_WORKER_PROCESSES:-1}" in service, (
        "one process, so a host paced per process stays paced"
    )


def test_arq_names_no_process_count() -> None:
    compose = _render(
        "docker-compose.yml",
        include_worker=True,
        include_redis=True,
        worker_backend="arq",
        **{PLUGINS_ANSWER_KEY: [_plugin()]},
    )
    service = compose[compose.index("  worker-crawler:") :]
    assert "WORKER_PROCESSES" not in service.split("\n\n")[0]


def test_without_a_worker_the_queue_gets_nothing() -> None:
    compose = _render(
        "docker-compose.yml", include_worker=False, **{PLUGINS_ANSWER_KEY: [_plugin()]}
    )
    assert "worker-crawler" not in compose


def test_dev_mounts_the_plugins_worker() -> None:
    overlay = _render(
        "docker-compose.dev.yml",
        include_worker=True,
        worker_backend="taskiq",
        **{PLUGINS_ANSWER_KEY: [_plugin()]},
    )
    assert "  worker-crawler:\n    volumes:\n      - .:/code" in overlay
