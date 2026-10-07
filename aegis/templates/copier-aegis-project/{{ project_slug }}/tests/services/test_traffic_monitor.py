"""TrafficMonitor (the "who's hammering you" store), in-memory backend.

Constructs ``TrafficMonitor(redis_url=None)`` directly so the tests are
self-contained - no Redis server needed, same approach the cache tests take.
The Redis backend shares the exact same logic paths; what's exercised here is
the bucketing, share math, dominance flag, and fail-open behavior.
"""

from __future__ import annotations

from app.components.backend.middleware.traffic import TrafficMonitor


def _monitor() -> TrafficMonitor:
    return TrafficMonitor(redis_url=None)


async def test_backend_label_is_memory_without_redis():
    assert _monitor().backend == "memory"


async def test_ranks_sources_by_volume_with_shares():
    m = _monitor()
    for _ in range(80):
        await m.record("9.9.9.9")
    for _ in range(15):
        await m.record("1.1.1.1")
    for _ in range(5):
        await m.record("2.2.2.2")

    snap = await m.snapshot(
        window_hours=1, limit=10, dominance_share=0.5, dominance_floor=100
    )
    assert snap["total_requests"] == 100
    assert [s["ip"] for s in snap["sources"]] == ["9.9.9.9", "1.1.1.1", "2.2.2.2"]
    assert snap["sources"][0]["requests"] == 80
    assert snap["sources"][0]["share"] == 0.8


async def test_dominant_flag_fires_above_both_thresholds():
    m = _monitor()
    for _ in range(150):
        await m.record("8.8.8.8")

    snap = await m.snapshot(
        window_hours=1, limit=10, dominance_share=0.5, dominance_floor=100
    )
    assert snap["dominant"] is not None
    assert snap["dominant"]["ip"] == "8.8.8.8"


async def test_dominant_flag_suppressed_under_floor():
    m = _monitor()
    # 100% share but only 30 requests - below the absolute floor.
    for _ in range(30):
        await m.record("8.8.8.8")

    snap = await m.snapshot(
        window_hours=1, limit=10, dominance_share=0.5, dominance_floor=100
    )
    assert snap["dominant"] is None


async def test_dominant_flag_suppressed_under_share():
    m = _monitor()
    # Plenty of volume, but no single source dominates.
    for ip in [f"10.0.0.{i}" for i in range(10)]:
        for _ in range(50):
            await m.record(ip)

    snap = await m.snapshot(
        window_hours=1, limit=20, dominance_share=0.5, dominance_floor=100
    )
    assert snap["total_requests"] == 500
    assert snap["dominant"] is None  # each IP is only 10%


async def test_blank_ip_is_ignored():
    m = _monitor()
    await m.record(None)
    await m.record("")
    snap = await m.snapshot(
        window_hours=1, limit=10, dominance_share=0.5, dominance_floor=1
    )
    assert snap["total_requests"] == 0
    assert snap["sources"] == []


async def test_reset_clears_state():
    m = _monitor()
    await m.record("1.2.3.4")
    m.reset()
    snap = await m.snapshot(
        window_hours=1, limit=10, dominance_share=0.5, dominance_floor=1
    )
    assert snap["total_requests"] == 0


async def test_empty_snapshot_shape():
    snap = await _monitor().snapshot(
        window_hours=6, limit=10, dominance_share=0.5, dominance_floor=100
    )
    assert snap == {
        "backend": "memory",
        "window_hours": 6,
        "total_requests": 0,
        "sources": [],
        "dominant": None,
    }


def test_the_suite_never_counts_into_a_real_redis() -> None:
    """The app's monitor is built at import from ``redis_url_effective``,
    which on the host is the running dev stack's Redis: every test request
    would land in its traffic panel."""
    from app.components.backend.middleware import traffic

    assert traffic.traffic_monitor.backend == "memory"
