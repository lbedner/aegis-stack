"""Everything the stack uses at once (``ui_resources``, which says what)."""

from typing import Any

import pytest

from app.core import series
from app.services.system import ui_resources, ui_runtime
from app.services.system.models import LoadCosts
from app.services.system.ui_logs import color_of
from tests._fake_runtime import (
    HOST,
    REDIS,
    STATS,
    STOPPED,
    WORKER,
    FakeRuntime,
    MiB,
    use_host_checks,
    use_load_costs,
    use_runtime,
)


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> Any:
    def reading(memory_percent: float = 50.0, cpu_percent: float = 10.0) -> None:
        use_host_checks(monkeypatch, memory_percent, cpu_percent)

    # The host's size comes from the runtime; a test may install its own.
    use_runtime(monkeypatch, FakeRuntime())

    reading()
    return reading


def _split(view: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in view["split"] if s["key"] == key)


async def test_this_stack_is_its_containers_summed(
    monkeypatch: pytest.MonkeyPatch, host: Any
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER))
    view = await ui_resources.overview()
    assert _split(view, "memory")["stack"] == 2 * STATS.memory_used
    assert _split(view, "cpu")["stack"] == 2 * STATS.cpu_percent


async def test_the_rest_is_what_the_host_uses_beyond_this_stack(
    monkeypatch: pytest.MonkeyPatch, host: Any
) -> None:
    """Half of the host's memory in use, a tenth of its four cores busy."""
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER))
    view = await ui_resources.overview()
    memory, cpu = _split(view, "memory"), _split(view, "cpu")
    assert memory["total"] == HOST.memory
    assert memory["rest"] == HOST.memory // 2 - 2 * STATS.memory_used
    assert memory["free"] == HOST.memory // 2
    # CPU in percent of one core, out of every core: 10% of 4 cores is 40.
    assert cpu["total"] == HOST.cpus * 100
    assert cpu["rest"] == pytest.approx(40 - 2 * STATS.cpu_percent)
    assert cpu["free"] == pytest.approx(HOST.cpus * 100 - 40)


async def test_the_rest_is_never_below_nothing(
    monkeypatch: pytest.MonkeyPatch, host: Any
) -> None:
    """The host check and the containers are read moments apart: a stack
    that reads more than the host's in-use leaves no rest, not a negative."""
    host(memory_percent=0.0, cpu_percent=0.0)
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER))
    view = await ui_resources.overview()
    assert _split(view, "memory")["rest"] == 0
    assert _split(view, "cpu")["rest"] == 0


async def test_every_container_heaviest_first_with_its_share(
    monkeypatch: pytest.MonkeyPatch, host: Any
) -> None:
    """Running ones by memory, each with its page and its share of the
    stack; a stopped one last, sharing nothing."""
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, STOPPED))
    rows = (await ui_resources.overview())["rows"]
    assert {r["name"] for r in rows} == {REDIS.name, WORKER.name, STOPPED.name}
    assert rows[-1]["name"] == STOPPED.name and rows[-1]["share"] is None
    running = [r for r in rows if r["share"] is not None]
    assert sum(r["share"] for r in running) == pytest.approx(100)
    assert {r["title"] for r in running} == {"Cache", "Worker"}


async def test_without_a_deploy_target_it_says_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, host: Any
) -> None:
    use_runtime(monkeypatch, FakeRuntime(REDIS, backend_name="none"))
    view = await ui_resources.overview()
    assert view["rows"] == [] and "aegis add deploy" in view["note"]


async def test_a_server_on_the_host_is_named_not_counted(
    monkeypatch: pytest.MonkeyPatch, host: Any
) -> None:
    """Ollama on the host has no container to read: named, with why."""
    if not ui_runtime.host_of("inference"):
        pytest.skip("no server that runs on the host in this stack")
    use_runtime(monkeypatch, FakeRuntime(REDIS))
    outside = (await ui_resources.overview())["outside"]
    assert [o["page"] for o in outside] == ["inference"]
    assert outside[0]["note"]


# The charts: each figure over time, a line per part (its containers added
# together), stacked so the top edge is this stack; the host's in use dashed
# across CPU and memory.
CONTAINERS = ui_runtime.SAMPLER


def _lines(chart: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["label"]: line for line in chart["data"]["series"]}


async def _charts() -> dict[str, dict[str, Any]]:
    return {chart["key"]: chart for chart in await ui_resources.charts(900)}


async def test_a_line_a_part_its_containers_added_together() -> None:
    await series.record(
        {
            f"{CONTAINERS}:worker:app-worker-system-1:memory": 100.0,
            f"{CONTAINERS}:worker:app-worker-media-1:memory": 50.0,
            f"{CONTAINERS}:redis:app-redis-1:memory": 10.0,
        }
    )
    memory = (await _charts())["memory"]
    lines = _lines(memory)
    assert lines["Worker"]["values"] == [150.0]
    assert lines["Cache"]["values"] == [10.0]
    assert memory["data"]["style"] == "stacked"
    # Each part in its colour everywhere (``ui_logs.color_of``).
    assert lines["Cache"]["color"] == color_of("redis")


async def test_a_part_reads_as_one_line_on_every_chart() -> None:
    """Network and disk add in and out (read and write) into the part's one
    line, so four charts read alike."""
    for total in (1000.0, 3000.0):
        await series.record(
            {
                f"{CONTAINERS}:redis:app-redis-1:net_in": total,
                f"{CONTAINERS}:redis:app-redis-1:net_out": total,
            }
        )
    charts = await _charts()
    assert list(charts) == ["cpu", "memory", "network", "disk"]
    assert list(_lines(charts["network"])) == ["Cache"]


async def test_the_host_in_use_runs_dashed_across_cpu_and_memory(host: Any) -> None:
    """Half the memory in use, a tenth of four cores: the gap between it and
    this stack's top edge is the rest of the host."""
    await series.sample(ui_resources.HOST)
    charts = await _charts()
    memory = _lines(charts["memory"])[ui_resources.HOST_LINE]
    assert memory["dashed"] is True
    assert memory["values"] == [pytest.approx(HOST.memory / 2, rel=0.01)]
    cpu = _lines(charts["cpu"])[ui_resources.HOST_LINE]
    assert cpu["values"] == [pytest.approx(40.0)]
    assert ui_resources.HOST_LINE not in _lines(charts["network"])


async def test_every_line_shares_the_stacks_ticks(host: Any) -> None:
    """The two samplers read at their own moments: the host's line holds its
    last reading on each of the stack's ticks, and a part not read at one
    (a container just started) is nothing there, so no line has a hole."""
    await series.record({f"{CONTAINERS}:redis:app-redis-1:memory": 10.0})
    await series.sample(ui_resources.HOST)
    await series.record(
        {
            f"{CONTAINERS}:redis:app-redis-1:memory": 12.0,
            f"{CONTAINERS}:worker:app-worker-system-1:memory": 5.0,
        }
    )
    # A window short enough that every tick is its own point (no buckets).
    charts = await ui_resources.charts(ui_resources.MAX_POINTS)
    memory = next(c for c in charts if c["key"] == "memory")["data"]
    lines = _lines({"data": memory})
    assert len(memory["labels"]) == 2
    assert lines["Worker"]["values"] == [0.0, 5.0]
    assert lines["Cache"]["values"] == [10.0, 12.0]
    assert lines[ui_resources.HOST_LINE]["values"][0] is None  # not read yet
    assert lines[ui_resources.HOST_LINE]["values"][1] == pytest.approx(
        HOST.memory / 2, rel=0.01
    )


async def test_what_each_part_costs_to_load_largest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_load_costs(
        monkeypatch,
        LoadCosts(core=60 * MiB, parts={"service_rag": 9 * MiB, "backend": 108 * MiB}),
    )
    found = await ui_resources.load_costs()
    assert [(r["key"], r["label"], r["value"]) for r in found["rows"]] == [
        ("backend", "Server", "108.0 MB"),
        ("service_rag", "RAG", "9.0 MB"),
    ]
    assert found["core"] == "60.0 MB"


async def test_a_service_named_like_a_component_says_which_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``app.services.scheduler`` is the job history the webserver reads,
    not the scheduler's own container."""
    use_load_costs(
        monkeypatch, LoadCosts(core=1, parts={"service_scheduler": 2, "service_rag": 3})
    )
    labels = [row["label"] for row in (await ui_resources.load_costs())["rows"]]
    assert labels == ["RAG", "Scheduler history"]
