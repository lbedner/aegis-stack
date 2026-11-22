"""Caps that hold across processes (``app.core.limits``): a budget a window
counts against, and slots held at once. Counted on the shared cache, so a
stack with Redis caps every process together and one without caps each."""

import pytest

from app.core import limits
from app.core.cache import CacheService
from app.core.config import settings
from tests._fake_redis import on_fake_redis

CAP, WINDOW = "RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW"


@pytest.fixture(params=["memory", "redis"])
def cache(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> CacheService:
    found = CacheService()
    if request.param == "redis":
        on_fake_redis(found)
    monkeypatch.setattr(limits, "get_cache", lambda: found)
    monkeypatch.setattr(settings, CAP, 2)
    monkeypatch.setattr(settings, WINDOW, 60)
    return found


class TestBudget:
    async def test_it_allows_up_to_its_cap_in_a_window(
        self, cache: CacheService
    ) -> None:
        budget = limits.Budget("starts", CAP, WINDOW)
        assert [await budget.take("1.2.3.4") for _ in range(3)] == [True, True, False]

    async def test_each_key_has_its_own_pool(self, cache: CacheService) -> None:
        budget = limits.Budget("starts", CAP, WINDOW)
        for _ in range(2):
            await budget.take("guest")
        assert await budget.take("guest") is False
        assert await budget.take("member") is True

    async def test_a_new_window_starts_over(
        self, cache: CacheService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        budget = limits.Budget("starts", CAP, WINDOW)
        for _ in range(3):
            await budget.take("k")
        monkeypatch.setattr(limits.time, "time", lambda: 10**12)
        assert await budget.take("k") is True

    async def test_a_cap_of_zero_is_off(
        self, cache: CacheService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, CAP, 0)
        budget = limits.Budget("starts", CAP, WINDOW)
        assert all([await budget.take("k") for _ in range(5)])


class TestSlots:
    async def test_it_holds_up_to_its_cap_and_frees_on_release(
        self, cache: CacheService
    ) -> None:
        slots = limits.Slots("calls", CAP)
        assert [await slots.take("guests") for _ in range(3)] == [True, True, False]
        await slots.release("guests")
        assert await slots.take("guests") is True


class _Down:
    """A cache whose Redis is unreachable."""

    async def count(self, key: str, by: int, ttl: int) -> int:
        raise ConnectionError("redis down")


async def test_an_unreachable_cache_lets_everyone_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(limits, "get_cache", lambda: _Down())
    monkeypatch.setattr(settings, CAP, 1)
    assert await limits.Budget("starts", CAP, WINDOW).take("k") is True
    slots = limits.Slots("calls", CAP)
    assert await slots.take("k") is True
    await slots.release("k")
