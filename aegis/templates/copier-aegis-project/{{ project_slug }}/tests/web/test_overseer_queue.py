"""The worker's queue on Overseer's maps (``topology.QUEUE``): where every
enqueue lands and the worker takes work from, drawn between them with what
waits in it, warning as it backs up and down with the Redis it lives in;
and the Flow view, which draws the stack's work through it."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip(
    "app.services.system.health_worker_rules", reason="no worker in this stack"
)

from app.components.web_frontend import overseer_container  # noqa: E402
from app.services.system import topology  # noqa: E402
from app.services.system.models import (  # noqa: E402
    ComponentStatus,
    ComponentStatusType,
)
from tests._fake_runtime import (  # noqa: E402
    REDIS,
    FakeRuntime,
    queue_status,
    use_runtime,
    worker_status,
)
from tests.web.dom import none, one, select, text  # noqa: E402
from tests.web.overseer import (  # noqa: E402
    CACHE,
    page_html,
    reported_only,
    sign_in,
    status_with,
)


def _queued(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, *queues: ComponentStatus
) -> TestClient:
    """A Server, a Worker over ``queues`` and the Cache whose Redis holds them."""
    server = ComponentStatus(name="backend", message="FastAPI", metadata={})
    worker = worker_status(*queues, message="2 queues")
    sign_in(app, monkeypatch, status_with(server, worker, CACHE))
    reported_only(monkeypatch)
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    return TestClient(app)


def test_the_map_shows_the_queue_between_who_enqueues_and_the_worker(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The queue is what the async lines meet at: drawn as a queue, with
    what waits in it and what is running now, and the Redis it lives in."""
    client = _queued(
        app, monkeypatch, queue_status("system", queued_jobs=12, jobs_ongoing=3)
    )
    html = page_html(client, "/overseer?view=map")
    queue = one(html, f'[data-node="{topology.QUEUE}"]')
    assert queue.get("data-role") == topology.Role.QUEUE
    assert "12 queued" in text(queue) and "3 running" in text(queue)
    assert "Redis" in text(queue)
    into = {
        p.get("data-from"): p.get("data-queued") is not None
        for p in select(html, f'svg path[data-to="{topology.QUEUE}"]')
    }
    assert into == {"backend": True, "worker": True}
    none(page_html(client, "/overseer?view=cards"), f'[data-card="{topology.QUEUE}"]')


def test_a_backed_up_queue_warns_and_says_why(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    backed_up = queue_status(
        "system", queued_jobs=40, oldest_waiting_seconds=720, max_wait_seconds=300
    )
    html = page_html(_queued(app, monkeypatch, backed_up), "/overseer?view=map")
    queue = one(html, f'[data-node="{topology.QUEUE}"]')
    assert queue.get("data-tone") == "warn"
    assert "backed up" in text(queue)


def test_a_queue_is_down_with_the_redis_it_lives_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = ComponentStatus(
        name="cache", status=ComponentStatusType.UNHEALTHY, message="Refused"
    )
    worker = worker_status(queue_status("system"))
    sign_in(app, monkeypatch, status_with(down, worker))
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    html = page_html(TestClient(app), "/overseer?view=map")
    queue = one(html, f'[data-node="{topology.QUEUE}"]')
    assert queue.get("data-tone") == "error"
    assert text(one(queue, "[data-cause]")) == "Likely cause: Cache"


def test_the_flow_view_draws_the_stack_left_to_right_in_its_shapes(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The high level: every process and store in its shape, work flowing
    from the Server through the queue to the Worker, the queue saying what
    waits in it, and a key to the shapes beneath."""
    client = _queued(app, monkeypatch, queue_status("system", queued_jobs=12))
    html = page_html(client, f"/overseer?view={overseer_container.FLOW_VIEW}")
    one(html, "[data-map][data-compact][data-across]")
    queue = one(html, f'[data-node="{topology.QUEUE}"]')
    assert queue.get("data-role") == topology.Role.QUEUE
    assert "12 queued" in text(one(queue, "[data-figure]"))
    line = one(html, f'svg path[data-from="{topology.QUEUE}"][data-to="worker"]')
    assert line.get("data-queued") is not None
    legend = text(one(html, "[data-legend]"))
    for role in (topology.Role.STORE, topology.Role.QUEUE):
        assert topology.ROLE_LABELS[role] in legend
    none(html, "[data-chip]")  # the high level: no services inside the Server
