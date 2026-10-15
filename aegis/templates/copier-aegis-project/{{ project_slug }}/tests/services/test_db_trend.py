"""How each table's rows changed today (``db_trend``): the first count the
database health check reads each UTC day is kept in the shared cache, and
Tables says the change since."""

from datetime import UTC, datetime

import pytest

from app.core.cache import CacheService
from app.services.system import db_trend

MORNING = datetime(2026, 10, 15, 0, 5, tzinfo=UTC)
NOON = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
TOMORROW = datetime(2026, 10, 16, 0, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def cache(monkeypatch: pytest.MonkeyPatch) -> CacheService:
    found = CacheService()
    monkeypatch.setattr(db_trend, "get_cache", lambda: found)
    return found


async def test_the_days_first_count_is_kept() -> None:
    """Later reads that day keep it; a table first seen later starts then;
    a count the database does not know (PostgreSQL's -1, never analysed)
    is none."""
    await db_trend.note({"user": 100, "org": -1}, now=MORNING)
    await db_trend.note({"user": 112, "post": 4}, now=NOON)
    kept = await db_trend.baselines(now=NOON)
    assert kept == {"user": (100, MORNING), "post": (4, NOON)}
    assert await db_trend.baselines(now=TOMORROW) == {}


def test_the_change_says_since_when() -> None:
    """Since the day began when the baseline was read within its first hour,
    else since the time it was; nothing for no change or no baseline."""
    assert db_trend.change(112, (100, MORNING)) == "+12 today"
    assert db_trend.change(98, (100, MORNING)) == "-2 today"
    assert db_trend.change(5, (4, NOON)) == "+1 since 12:00 UTC"
    assert db_trend.change(100, (100, MORNING)) is None
    assert db_trend.change(100, None) is None
    assert db_trend.change(None, (100, MORNING)) is None


async def test_a_cache_that_fails_never_fails_the_health_check(
    cache: CacheService, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*_: object, **__: object) -> None:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(cache, "get", down)
    await db_trend.note({"user": 1}, now=MORNING)  # logged, not raised
    assert await db_trend.baselines(now=MORNING) == {}


async def test_the_health_check_keeps_each_tables_first_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The database health check, whichever engine's, keeps what it read."""
    from app.services.system import health_db
    from app.services.system.models import ComponentStatus

    async def checked() -> ComponentStatus:
        tables = [{"name": "user", "rows": 7}]
        return ComponentStatus(
            name="database", message="ok", metadata={"tables": tables}
        )

    monkeypatch.setattr(health_db, "_check_engine", checked)
    await health_db.check_database_health()
    assert set(await db_trend.baselines()) == {"user"}
