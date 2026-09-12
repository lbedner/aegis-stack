"""The system-status walk is shared: concurrent and repeated callers within
the TTL reuse one walk instead of each running every component check."""

import asyncio

import pytest

from app.services.system.health import (
    _health_checks,
    get_system_status,
    invalidate_status_cache,
    register_health_check,
)
from app.services.system.models import ComponentStatus, ComponentStatusType


def _counting_check(counter: dict[str, int]) -> object:
    async def check() -> ComponentStatus:
        counter["calls"] += 1
        return ComponentStatus(
            name="counted",
            status=ComponentStatusType.HEALTHY,
            message="ok",
            response_time_ms=1.0,
        )

    return check


@pytest.fixture
def counted_check():
    counter = {"calls": 0}
    register_health_check("counted", _counting_check(counter))
    yield counter
    _health_checks.pop("counted", None)
    invalidate_status_cache()


@pytest.mark.asyncio
async def test_repeated_calls_within_ttl_share_one_walk(counted_check) -> None:
    first = await get_system_status()
    second = await get_system_status()
    assert counted_check["calls"] == 1
    assert second is first


@pytest.mark.asyncio
async def test_concurrent_calls_share_one_walk(counted_check) -> None:
    results = await asyncio.gather(*(get_system_status() for _ in range(5)))
    assert counted_check["calls"] == 1
    assert all(r is results[0] for r in results)


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(counted_check) -> None:
    await get_system_status()
    await get_system_status(force_refresh=True)
    assert counted_check["calls"] == 2


@pytest.mark.asyncio
async def test_registering_a_check_invalidates_cache(counted_check) -> None:
    await get_system_status()
    counter2 = {"calls": 0}
    register_health_check("counted_2", _counting_check(counter2))
    try:
        await get_system_status()
    finally:
        _health_checks.pop("counted_2", None)
    assert counter2["calls"] == 1
    assert counted_check["calls"] == 2
