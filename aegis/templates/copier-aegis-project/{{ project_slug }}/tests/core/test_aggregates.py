"""What each part holds, as figures (``app.core.aggregates``): declared by
each part beside its data, found by its module's name, read through the
shared cache, over one of the app's windows."""

from contextlib import nullcontext
from datetime import datetime
import types
import typing

from pydantic import BaseModel
import pytest

from app.core import aggregates, discovery, ranges
from app.core.aggregates import Aggregate
from app.core.cache import CacheService
from app.core.figures import FIGURES


class Runs(BaseModel):
    model_config = FIGURES

    total: int


def _part(name: str, *declared: Aggregate) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        __name__=f"app.services.{name}.aggregates", AGGREGATES=declared
    )


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[int | None]:
    """The scheduler's job runs, declared; the windows each read was for."""
    found: list[int | None] = []

    async def runs(session: object, days: int | None) -> Runs:
        found.append(days)
        return Runs(total=3)

    parts = [_part("scheduler", Aggregate("runs", "Job runs", runs))]
    monkeypatch.setattr(discovery, "import_modules_named", lambda *_: parts)
    cache = CacheService()
    monkeypatch.setattr(aggregates, "get_cache", lambda: cache)
    monkeypatch.setattr(aggregates, "_session", nullcontext)
    return found


def test_each_parts_aggregates_are_named_after_their_part(
    asked: list[int | None],
) -> None:
    assert list(aggregates.declared()) == ["scheduler.runs"]


def test_a_name_claimed_twice_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not a silent winner: the second would hide the first."""

    async def runs(session: object, days: int | None) -> Runs:
        return Runs(total=0)

    twice = _part("scheduler", Aggregate("runs", "", runs), Aggregate("runs", "", runs))
    monkeypatch.setattr(discovery, "import_modules_named", lambda *_: [twice])

    with pytest.raises(ValueError, match="scheduler.runs"):
        aggregates.declared()


def test_a_part_declaring_none_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = types.SimpleNamespace(__name__="app.services.blog.aggregates")
    monkeypatch.setattr(discovery, "import_modules_named", lambda *_: [empty])

    with pytest.raises(ValueError, match="declares no AGGREGATES"):
        aggregates.declared()


async def test_two_asks_within_a_minute_read_once(asked: list[int | None]) -> None:
    """A burst of questions costs one query."""
    first = await aggregates.read("scheduler.runs", 7)
    again = await aggregates.read("scheduler.runs", 7)

    assert first == again == Runs(total=3)
    assert asked == [7]


async def test_a_window_is_one_of_the_apps(asked: list[int | None]) -> None:
    """The range chips' days, never their ``ALL`` stand-in; ``ALL``, or
    none, is all of it."""
    with pytest.raises(ValueError, match=r"1, 7, 14, 30, 90, 365, or none") as said:
        await aggregates.read("scheduler.runs", 5)
    assert str(ranges.ALL) not in str(said.value)

    await aggregates.read("scheduler.runs", ranges.ALL)
    await aggregates.read("scheduler.runs")

    assert asked == [None]  # the same window: read once


async def test_an_unknown_aggregate_names_the_known_ones(
    asked: list[int | None],
) -> None:
    with pytest.raises(ValueError, match="scheduler.runs"):
        await aggregates.read("scheduler.run", 7)


async def test_without_the_cache_it_reads_each_time(
    asked: list[int | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache saves a query; it never fails the read."""

    class Down(CacheService):
        async def get(self, key: str) -> None:
            raise ConnectionError("no Redis")

    down = Down()
    monkeypatch.setattr(aggregates, "get_cache", lambda: down)

    assert await aggregates.read("scheduler.runs", 7) == Runs(total=3)


def test_every_aggregate_this_app_declares_is_figures() -> None:
    """Never a row: each read returns a frozen model refusing what it does
    not declare, whose fields are figures and the labels they are grouped
    by (no list of rows, no nested record)."""
    for name, one in aggregates.declared().items():
        model = typing.get_type_hints(one.read)["return"]
        assert model.model_config.get("frozen") is True, name
        assert model.model_config.get("extra") == "forbid", name
        for field in model.model_fields.values():
            assert _figures(field.annotation), (name, field.annotation)


def _figures(annotation: object) -> bool:
    """A scalar, a timestamp, or a mapping of labels to figures."""
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Annotated:
        return _figures(args[0])
    if origin is dict:
        return args[0] is str and _figures(args[1])
    if origin in (types.UnionType, typing.Union):
        return all(_figures(arg) for arg in args)
    return annotation in (int, float, str, bool, datetime, type(None))
