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
from aegis.core.plugins.spec import (
    PluginKind,
    PluginSpec,
    WorkerQueueWiring,
)

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


class TestPluginQueueConcurrency:
    """A plugin's queue ships the concurrency it needs, not the default.

    A media conversion is an ffmpeg child holding a core; ten at once on a
    2-vCPU box makes the app unresponsive. The project could already
    override it with ``WORKER_QUEUES``, but a plugin could not ship the
    number — so every install started wrong (issue #1870).
    """

    def test_a_bare_name_still_works(self) -> None:
        """Back-compat: plugins predating the wiring keep `["crawler"]`."""
        spec = PluginSpec(
            name="crawl4ai",
            kind=PluginKind.SERVICE,
            description="d",
            worker_queues=["crawler"],
        )

        serialized = serialize_plugin_to_answer(spec)

        assert serialized["worker_queues"] == ["crawler"]
        assert serialized["worker_queue_settings"] == []

    def test_a_wiring_carries_its_concurrency(self) -> None:
        spec = PluginSpec(
            name="media",
            kind=PluginKind.SERVICE,
            description="d",
            worker_queues=[
                WorkerQueueWiring(name="media", concurrency=2, max_wait_seconds=900)
            ],
        )

        serialized = serialize_plugin_to_answer(spec)

        assert serialized["worker_queues"] == ["media"]
        assert serialized["worker_queue_settings"] == [
            {"name": "media", "concurrency": 2, "max_wait_seconds": 900}
        ]

    def test_the_defaults_module_renders_the_plugin_number(self) -> None:
        spec = PluginSpec(
            name="media",
            kind=PluginKind.SERVICE,
            description="d",
            worker_queues=[WorkerQueueWiring(name="media", concurrency=2)],
        )
        rendered = _render(
            "app/core/plugin_queue_defaults.py",
            include_worker=True,
            **{PLUGINS_ANSWER_KEY: [serialize_plugin_to_answer(spec)]},
        )

        assert '"media"' in rendered
        assert "concurrency=2" in rendered

    def test_a_stack_without_plugins_renders_an_empty_mapping(self) -> None:
        rendered = _render("app/core/plugin_queue_defaults.py", include_worker=True)

        assert "PLUGIN_QUEUE_DEFAULTS: dict[str, QueueWorker] = {}" in rendered
        assert "QueueWorker(" not in rendered

    def test_the_settings_merge_the_plugin_defaults(self) -> None:
        """``queue_workers.py`` is plain Python: read it, don't render it."""
        rendered = (
            get_template_path() / "{{ project_slug }}" / "app/core/queue_workers.py"
        ).read_text()

        assert "PLUGIN_QUEUE_DEFAULTS" in rendered
        assert "{**_STACK_QUEUES, **PLUGIN_QUEUE_DEFAULTS}" in rendered

    def test_an_env_override_still_wins(self) -> None:
        """The merged dict is only the field *default*: pydantic lets the
        `WORKER_QUEUES` environment replace it wholesale."""
        rendered = _render(
            "app/core/config.py", include_worker=True, worker_backend="arq"
        )

        assert "Field(default_factory=DEFAULT_QUEUES.copy)" in rendered
