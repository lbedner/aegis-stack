"""The containers behind an Overseer page (``ui_runtime.containers``): a row
per instance with what ``app.core.runtime`` reads, the same in htmx
and Flet; and, where there is nothing to read, why. The containers sampler
(``ui_runtime.sample``) reads every container once a tick and every viewer
is served from that one reading."""

import pytest

from app.core import series
from app.services.system import ui_runtime
from tests._fake_runtime import (
    REDIS,
    STATS,
    STOPPED,
    WORKER,
    FakeRuntime,
    use_runtime,
)


async def test_a_page_lists_its_own_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_runtime(monkeypatch, FakeRuntime(WORKER, STOPPED, REDIS))
    view = await ui_runtime.containers("worker")
    assert view["note"] is None
    running, stopped = view["rows"]
    assert running["name"] == "app-worker-system-1"
    assert running["state"] == "running (healthy)"
    assert running["cpu"] == "12.5%"
    assert "128.0 MB" in running["memory"] and "512.0 MB" in running["memory"]
    assert running["restarts"] == "2" and running["uptime"].startswith("3h")
    assert running["image"] == "app:latest abc1234"
    # A stopped container has no stats to read, and is not asked for any.
    assert stopped["state"] == "exited" and stopped["cpu"] == "-"
    assert "w1" in fake.asked and "w2" not in fake.asked


async def test_without_a_deploy_target_it_says_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    view = await ui_runtime.containers("redis")
    assert view["rows"] == [] and "aegis add deploy" in view["note"]


async def test_a_page_with_no_container_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    view = await ui_runtime.containers("database")
    assert view["rows"] == [] and "No container" in view["note"]


async def test_an_unreachable_runtime_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    use_runtime(monkeypatch, FakeRuntime(fail=True))
    view = await ui_runtime.containers("redis")
    assert view["rows"] == [] and "socket proxy" in view["note"]


def test_a_component_names_its_page() -> None:
    assert ui_runtime.page_of("backend") == "server"
    assert ui_runtime.page_of("cache") == "redis"
    assert ui_runtime.page_of("worker") == "worker"
    assert ui_runtime.page_of("auth") is None


async def test_one_reading_serves_every_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = use_runtime(monkeypatch, FakeRuntime(WORKER, STOPPED, REDIS))
    reading = await ui_runtime.sample()
    cpu, memory = ui_runtime.CPU, ui_runtime.MEMORY
    assert reading.values == {
        f"worker:app-worker-system-1:{cpu}": STATS.cpu_percent,
        f"worker:app-worker-system-1:{memory}": STATS.memory_used,
        f"redis:app-redis-1:{cpu}": STATS.cpu_percent,
        f"redis:app-redis-1:{memory}": STATS.memory_used,
    }
    await series.sample(series.Sampler(ui_runtime.SAMPLER, ui_runtime.sample))
    asked = (fake.listed, list(fake.asked))
    for _ in range(3):  # three viewers
        view = await ui_runtime.containers("redis")
    assert view["rows"][0]["name"] == "app-redis-1"
    assert (fake.listed, fake.asked) == asked  # no further runtime reads


async def test_reading_a_page_marks_the_sampler_watched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    await ui_runtime.containers("redis")
    assert await series.watched(ui_runtime.SAMPLER)


async def test_without_a_deploy_target_the_sampler_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    reading = await ui_runtime.sample()
    assert (reading.values, reading.latest, fake.listed) == ({}, None, 0)


async def test_the_charts_cover_the_window_asked_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    drawn = await ui_runtime.charts("redis", window=1800)
    assert drawn is not None
    cpu, _memory = drawn
    start, end = cpu["data"]["window"]
    assert end - start == 1800 * 1000
    assert cpu["subtitle"] == "Last 30 minutes"
    assert cpu["empty"] == "Nothing in the last 30 minutes."


async def test_before_the_first_sample_viewers_share_one_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback read goes through the sampler (claimed, and kept as its
    latest), so a second viewer does not read the runtime again."""
    fake = use_runtime(monkeypatch, FakeRuntime(REDIS))
    await ui_runtime.containers("redis")
    await ui_runtime.containers("redis")
    assert fake.listed == 1
