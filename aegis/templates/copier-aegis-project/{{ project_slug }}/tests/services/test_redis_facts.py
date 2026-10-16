"""What a key family holds, in its owner's words (``redis_facts``): how much
is in it, how much went through it and how recently, read from the data."""

import asyncio
from typing import Any

import pytest

from app.core.key_family import KeyFamily
from app.services.system import redis_facts, redis_keys
from app.services.system.models import EntryRow, FamilyFacts
from tests._fake_redis import FakeRedis

NOW = 1_800_000_000.0
STREAM = "aegis:events:worker"
EVENTS = KeyFamily(STREAM, "stream", "Worker events", "Events", "Worker", holds="event")
ERRORS = KeyFamily("errors:*:all", "zset", "Error history", "Index", "Errors")
TOTALS = KeyFamily(
    "traffic:total:*",
    "string",
    "Traffic totals",
    "Per hour",
    "Traffic",
    holds="request",
)


def _id(seconds: float, sequence: int = 0) -> str:
    return f"{int(seconds * 1000)}-{sequence}"


def _facts(family: KeyFamily, redis: FakeRedis, *keys: str) -> FamilyFacts:
    return asyncio.run(redis_facts.facts(family, redis, list(keys), now=NOW))


class TestTimes:
    def test_scores_that_are_times_read_as_seconds(self) -> None:
        assert redis_facts.as_seconds(NOW) == NOW
        assert redis_facts.as_seconds(NOW * 1000) == NOW
        assert redis_facts.as_seconds(41) is None  # a count, not a time

    def test_a_stream_entry_is_dated_by_its_id(self) -> None:
        assert redis_facts.entry_time(_id(NOW)) == NOW

    def test_the_last_hour_a_minute_at_a_time(self) -> None:
        counts = redis_facts.per_minute([NOW - 30, NOW - 31, NOW - 3599], NOW)
        assert len(counts) == 60
        assert counts[-1] == 2 and counts[0] == 1  # oldest first


class TestStream:
    def test_says_how_much_went_through_and_how_recently(self) -> None:
        redis = FakeRedis()
        redis.streams[STREAM] = [
            (_id(NOW - 7200), {"event_type": "job.started"}),
            (_id(NOW - 600), {"event_type": "job.ended"}),
            (_id(NOW - 20), {"event_type": "job.completed", "queue": "system"}),
        ]
        redis.added[STREAM] = 103
        redis.groups[STREAM] = [
            {"name": "overseer", "consumers": 1, "pending": 2, "lag": 0},
            {"name": "audit", "consumers": 0, "pending": 0, "lag": 7},
        ]
        facts = _facts(EVENTS, redis, STREAM)
        figures = dict(facts.figures)
        assert figures["Through it"] == "103 events"  # every entry it was given
        assert figures["Held now"] == "3 events"
        assert figures["Last minute"] == "1"
        assert figures["Last hour"] == "2"
        assert figures["Newest"] == "20s ago"
        assert facts.spark  # the last hour, drawn
        assert [g.name for g in facts.groups] == ["overseer", "audit"]
        assert [g.lag for g in facts.groups] == ["caught up", "7 behind"]

    def test_past_the_cap_the_newest_are_counted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A busier hour than the cap reads its newest entries, so the last
        minute is never the one left out."""
        monkeypatch.setattr(redis_facts, "RECENT_CAP", 2)
        redis = FakeRedis()
        redis.streams[STREAM] = [
            (_id(NOW - 3000), {}),
            (_id(NOW - 2000), {}),
            (_id(NOW - 10), {}),
            (_id(NOW - 5), {}),
        ]
        figures = dict(_facts(EVENTS, redis, STREAM).figures)
        assert figures["Last minute"] == "2+"
        assert figures["Last hour"] == "2+"


class TestSortedSet:
    def test_a_set_scored_by_time_counts_what_is_recent(self) -> None:
        redis = FakeRedis()
        redis.zsets["errors:dev:all"] = {"a": NOW - 7200, "b": NOW - 30, "c": NOW - 5}
        facts = _facts(ERRORS, redis, "errors:dev:all")
        figures = dict(facts.figures)
        assert figures["Held now"] == "3 members"  # no word of its own: the type's
        assert figures["Last hour"] == "2" and figures["Last minute"] == "2"
        assert figures["Oldest"] == "2h ago" and figures["Newest"] == "5s ago"
        assert facts.spark

    def test_scores_in_milliseconds_are_times_too(self) -> None:
        redis = FakeRedis()
        redis.zsets["errors:dev:all"] = {"a": (NOW - 90) * 1000}
        figures = dict(_facts(ERRORS, redis, "errors:dev:all").figures)
        assert figures["Last hour"] == "1" and figures["Last minute"] == "0"
        assert figures["Newest"] == "1m 30s ago"

    def test_a_key_of_another_type_is_left_out(self) -> None:
        """A family's pattern can match a key of another type (arq's queue
        family and its health-check string): the rest still read."""
        redis = FakeRedis()
        redis.zsets["errors:dev:all"] = {"a": NOW - 30}
        redis.strings["errors:dev:all:check"] = "ok"
        facts = _facts(ERRORS, redis, "errors:dev:all", "errors:dev:all:check")
        figures = dict(facts.figures)
        assert figures["Held now"] == "1 member"  # one, not "1 members"
        assert figures["Last hour"] == "1"

    def test_scores_that_are_counts_are_not_times(self) -> None:
        sources = KeyFamily("traffic:sources:*", "zset", "Sources", "Per IP", "T")
        redis = FakeRedis()
        redis.zsets["traffic:sources:1"] = {"10.0.0.1": 41, "10.0.0.2": 3}
        facts = _facts(sources, redis, "traffic:sources:1")
        assert dict(facts.figures) == {"Held now": "2 members"}
        assert facts.spark is None


class TestStrings:
    def test_counters_are_added_up_in_the_owners_word(self) -> None:
        redis = FakeRedis()
        redis.strings |= {"traffic:total:1": "40", "traffic:total:2": "2"}
        facts = _facts(TOTALS, redis, "traffic:total:1", "traffic:total:2")
        assert dict(facts.figures) == {"Total": "42 requests"}

    def test_values_that_are_not_numbers_are_not_added(self) -> None:
        redis = FakeRedis()
        redis.strings["traffic:total:1"] = "{}"
        assert _facts(TOTALS, redis, "traffic:total:1").figures == []

    def test_a_long_value_is_not_fetched_to_add(self) -> None:
        """A cached blob is a value, not a counter: its length rules it out
        before any of it is read."""
        redis = FakeRedis()
        redis.strings |= {"traffic:total:1": "4", "traffic:total:2": "x" * 4096}
        fetched: list[list[str]] = []

        async def mget(keys: list[str]) -> list[str | None]:
            fetched.append(keys)
            return []

        redis.mget = mget  # type: ignore[method-assign]
        facts = _facts(TOTALS, redis, "traffic:total:1", "traffic:total:2")
        assert facts.figures == [] and fetched == []


class TestPartial:
    def test_a_family_with_more_keys_than_are_read_says_so(self) -> None:
        redis = FakeRedis()
        keys = [f"errors:{i}:all" for i in range(redis_facts.FACT_KEYS + 1)]
        assert _facts(ERRORS, redis, *keys).partial == redis_facts.FACT_KEYS
        assert _facts(ERRORS, redis, *keys[:3]).partial == 0


class TestRows:
    def test_a_stream_entry_reads_as_its_fields_and_when(self) -> None:
        pairs = [
            (_id(NOW - 20), {b"event_type": b"job.completed", b"queue": b"system"})
        ]
        assert redis_facts.readable("stream", pairs, now=NOW) == [
            EntryRow(
                a=_id(NOW - 20),
                b="event_type=job.completed · queue=system",
                when="20s ago",
            )
        ]

    def test_a_time_score_reads_as_when(self) -> None:
        rows = redis_facts.readable("zset", [(b"job-1", NOW - 90)], now=NOW)
        assert rows == [EntryRow(a="job-1", b="1799999910", when="1m 30s ago")]

    def test_other_values_read_as_they_are(self) -> None:
        rows = redis_facts.readable("zset", [(b"10.0.0.1", 41.0)], now=NOW)
        assert rows == [EntryRow(a="10.0.0.1", b="41")]


class TestDetail:
    def test_a_family_holding_a_credential_is_never_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = KeyFamily("secret:*", "list", "Secret", "Tokens", "X", peek=False)

        def no_client(db: int = 0) -> Any:
            raise AssertionError("read")

        monkeypatch.setattr(redis_keys, "families", lambda: [secret])
        monkeypatch.setattr(redis_keys, "redis_client", no_client)
        found = asyncio.run(redis_facts.detail(0))
        assert found is not None
        assert found.rows == [] and found.facts == FamilyFacts()

    def test_the_newest_key_is_the_one_the_map_saw(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The keyspace map already knows which key was touched last: the
        detail reads that one rather than scanning every key to find it."""
        redis = FakeRedis()
        redis.zsets |= {"errors:a:all": {"x": NOW}, "errors:b:all": {"y": NOW}}
        monkeypatch.setattr(redis_keys, "families", lambda: [ERRORS])
        monkeypatch.setattr(redis_keys, "redis_client", lambda db=0: redis)
        found = asyncio.run(redis_facts.detail(0, "errors:b:all"))
        assert found is not None
        assert found.key == "errors:b:all"
        assert [row.a for row in found.rows] == ["y"]

    def test_an_unknown_family_is_none(self) -> None:
        assert asyncio.run(redis_facts.detail(10_000)) is None
