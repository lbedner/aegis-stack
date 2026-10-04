"""The containers behind an Overseer page (``ui_runtime.containers``): a row
per instance with what ``app.core.runtime`` reads, the same in htmx
and Flet; and, where there is nothing to read, why. The containers sampler
(``ui_runtime.sample``) reads every container once a tick and every viewer
is served from that one reading."""

import pytest

from app.core import series
from app.core.config import settings
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
    figures = {
        ui_runtime.CPU: STATS.cpu_percent,
        ui_runtime.MEMORY: STATS.memory_used,
        # Running totals: a chart reads them as bytes per second.
        ui_runtime.NET_IN: STATS.network_rx,
        ui_runtime.NET_OUT: STATS.network_tx,
        ui_runtime.DISK_READ: STATS.disk_read,
        ui_runtime.DISK_WRITE: STATS.disk_write,
    }
    assert reading.values == {
        f"{page}:{name}:{metric}": value
        for page, name in (("worker", "app-worker-system-1"), ("redis", "app-redis-1"))
        for metric, value in figures.items()
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
    cpu, _memory, _network, _disk = drawn
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


async def test_network_and_disk_chart_as_bytes_per_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker counts network and disk in running totals; the charts read the
    rate between two readings, one line per direction, and a total that
    went down (the container restarted) is no rate at all."""
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    clock = [1000.0]
    monkeypatch.setattr(series.time, "time", lambda: clock[0])
    base = "redis:app-redis-1:"
    for rx, tx in ((1_000, 500), (3_000, 900), (100, 50)):
        await series.record(
            {
                f"{ui_runtime.SAMPLER}:{base}{ui_runtime.NET_IN}": rx,
                f"{ui_runtime.SAMPLER}:{base}{ui_runtime.NET_OUT}": tx,
            }
        )
        clock[0] += 2.0
    drawn = {c["key"]: c for c in await ui_runtime.charts("redis", window=900)}
    data = drawn["network"]["data"]
    assert data["format"] == "bytes_per_second"
    lines = {line["label"]: line["values"] for line in data["series"]}
    assert lines == {"app-redis-1 in": [1000.0], "app-redis-1 out": [200.0]}
    assert [c["title"] for c in drawn.values()] == [
        "CPU",
        "Memory",
        "Network",
        "Disk I/O",
    ]


async def test_a_pages_trend_sums_its_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A card's sparklines: the page's CPU and memory over the window, each
    tick's containers added together (the Worker page's two, one line)."""
    use_runtime(monkeypatch, FakeRuntime(WORKER, REDIS))
    clock = [1000.0]
    monkeypatch.setattr(series.time, "time", lambda: clock[0])
    for cpu in (10.0, 20.0):
        await series.record(
            {
                f"{ui_runtime.SAMPLER}:worker:a-1:{ui_runtime.CPU}": cpu,
                f"{ui_runtime.SAMPLER}:worker:b-1:{ui_runtime.CPU}": 1.0,
                f"{ui_runtime.SAMPLER}:worker:a-1:{ui_runtime.MEMORY}": 100.0,
            }
        )
        clock[0] += 1.0
    assert await ui_runtime.trends(["worker", "redis"], window=900) == {
        "worker": {"cpu": [11.0, 21.0], "memory": [100.0, 100.0]},
        "redis": {"cpu": [], "memory": []},
    }


async def test_several_pages_are_served_from_one_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overseer's home asks for every page each frame: one read for all."""
    use_runtime(monkeypatch, FakeRuntime(WORKER, REDIS))
    await ui_runtime.containers("redis")  # the sampler's first reading
    reads: list[str] = []
    current = series.current

    async def counted(*args: object, **kwargs: object) -> object:
        reads.append("current")
        return await current(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(series, "current", counted)
    found = await ui_runtime.containers_of(["redis", "worker", "database"])
    assert reads == ["current"]
    assert [r["name"] for r in found["redis"]["rows"]] == [REDIS.name]
    assert [r["name"] for r in found["worker"]["rows"]] == [WORKER.name]
    assert "No container" in found["database"]["note"]


async def test_cpu_and_memory_say_when_they_pass_their_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """By the host checks' own rule (``usage_status``): a warning from 80%
    of the alert threshold, unhealthy at it. Memory is a share of its
    limit, CPU of the cores it can use."""
    monkeypatch.setattr(settings, "MEMORY_THRESHOLD_PERCENT", 30.0)  # 25% >= 24
    monkeypatch.setattr(settings, "CPU_THRESHOLD_PERCENT", 10.0)  # 12.5% >= 10
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    (row,) = (await ui_runtime.containers("redis"))["rows"]
    assert (row["memory_status"], row["cpu_status"]) == ("warning", "unhealthy")


async def test_cpu_and_memory_charts_mark_where_warning_and_alert_begin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MEMORY_THRESHOLD_PERCENT", 90.0)
    monkeypatch.setattr(settings, "CPU_THRESHOLD_PERCENT", 80.0)
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    await ui_runtime.containers("redis")  # the reading the limits come from
    charts = {c["key"]: c["data"] for c in await ui_runtime.charts("redis")}
    limit = STATS.memory_limit
    assert charts[ui_runtime.MEMORY]["thresholds"] == [
        {"value": pytest.approx(limit * 0.72), "tone": "warn"},
        {"value": pytest.approx(limit * 0.9), "tone": "error"},
    ]
    assert charts[ui_runtime.CPU]["thresholds"] == [
        {"value": pytest.approx(64.0), "tone": "warn"},
        {"value": pytest.approx(80.0), "tone": "error"},
    ]
    assert not charts["network"].get("thresholds")  # no limit to pass


async def test_where_a_warning_starts_is_a_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WARNING_PERCENT_OF_THRESHOLD`` (Overseer > Settings, Health): at 50
    a 40% memory threshold warns from 20%, on the figure and the chart."""
    monkeypatch.setattr(settings, "WARNING_PERCENT_OF_THRESHOLD", 50.0)
    monkeypatch.setattr(settings, "MEMORY_THRESHOLD_PERCENT", 40.0)
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    (row,) = (await ui_runtime.containers("redis"))["rows"]  # 25% used
    assert row["memory_status"] == "warning"
    charts = {c["key"]: c["data"] for c in await ui_runtime.charts("redis")}
    warn, _alert = charts[ui_runtime.MEMORY]["thresholds"]
    assert warn["value"] == pytest.approx(STATS.memory_limit * 0.2)
