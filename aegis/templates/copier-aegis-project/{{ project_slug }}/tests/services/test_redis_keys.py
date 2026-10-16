"""The Redis keyspace map: which part of the app owns each key, and how the
map draws them."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pytest

import app
from app.services.system import redis_keys
from app.services.system.models import KeyProbe
from app.services.system.redis_keys import KeyFamily
from tests._fake_redis import FakeRedis as SharedRedis

FAMILIES = (
    KeyFamily(
        "traffic:sources:*", "zset", "Traffic sources", "Per-IP counts", "Backend"
    ),
    KeyFamily("traffic:*", "string", "Traffic other", "Anything else", "Backend"),
)


class TestClaiming:
    def test_the_first_family_that_matches_claims_a_key(self) -> None:
        groups, unclaimed = redis_keys.group_keys(
            FAMILIES, ["traffic:sources:1", "traffic:total:1", "stray"]
        )
        assert groups == {0: ["traffic:sources:1"], 1: ["traffic:total:1"]}
        assert unclaimed == ["stray"]

    def test_the_app_declares_its_own_keys(self) -> None:
        """Owners declare their keys beside the code that writes them."""
        patterns = {f.pattern for f in redis_keys.families()}
        assert "traffic:sources:*" in patterns


class TestWaffle:
    """The keyspace grid: a cell per key while they fit, shares after."""

    def test_one_cell_per_key_when_they_fit(self) -> None:
        assert redis_keys.waffle([2, 1], cells=6) == [0, 0, 1, None, None, None]

    def test_proportional_when_crowded(self) -> None:
        cells = redis_keys.waffle([90, 10], cells=10)
        assert cells.count(0) == 9 and cells.count(1) == 1

    def test_every_family_with_keys_keeps_a_cell(self) -> None:
        cells = redis_keys.waffle([1000, 0, 1], cells=10)
        assert len(cells) == 10
        assert cells.count(2) == 1 and 1 not in cells

    def test_an_empty_keyspace_is_all_empty_cells(self) -> None:
        assert redis_keys.waffle([0, 0], cells=4) == [None] * 4


class TestSummary:
    def test_sizes_the_family_from_its_samples(self) -> None:
        probes = {
            "a": KeyProbe(ttl=60, idle=2, bytes=100),
            "b": KeyProbe(ttl=30, idle=50, bytes=300),
        }
        summary = redis_keys.summarize(["a", "b", "c"], probes)
        assert summary.count == 3
        assert summary.memory == 600  # average sample size times the count
        assert summary.idle == 2
        assert summary.active is True
        assert summary.latest == "a"  # the most recently touched

    def test_a_quiet_family_is_not_active(self) -> None:
        probes = {"a": KeyProbe(idle=3600, bytes=10)}
        assert redis_keys.summarize(["a"], probes).active is False


class TestShown:
    def test_text_reads_as_text_and_binary_says_so(self) -> None:
        assert redis_keys.shown(b"10.0.0.1") == "10.0.0.1"
        assert redis_keys.shown(b"\x80\x04\x95") == "binary, 3 bytes"
        assert redis_keys.shown(5.0) == "5"


class TestEstimate:
    """Past the scan cap, a family's count is its share of the scan scaled
    to the database's real size."""

    def test_a_full_scan_counts_exactly(self) -> None:
        assert redis_keys.estimate(40, scanned=100, size=100) == 40

    def test_a_capped_scan_scales_to_the_database(self) -> None:
        assert redis_keys.estimate(40, scanned=10_000, size=1_000_000) == 4_000

    def test_an_empty_scan_estimates_nothing(self) -> None:
        assert redis_keys.estimate(0, scanned=0, size=0) == 0


class TestProbe:
    """Activity is checked on every scanned key: one hot key among
    thousands of cold ones still lights its family."""

    @pytest.mark.asyncio
    async def test_the_hot_key_is_found_however_deep_it_sits(self) -> None:
        keys = [f"traffic:sources:{i}" for i in range(500)]
        idle = {k: 3600 for k in keys} | {keys[-1]: 0}
        redis = FakeRedis(idle)
        probes, idle_of = await redis_keys.probe(redis, [keys])
        summary = redis_keys.summarize(keys, probes, idle_of)
        assert not [op for op, _ in redis.calls if op == "type"]  # nothing reads it
        assert summary.active is True
        assert summary.latest == keys[-1]


class FakeRedis:
    """Just enough of a pipeline: every command answers from ``idle``."""

    def __init__(self, idle: dict[str, int]) -> None:
        self.idle = idle
        self.calls: list[tuple[str, str]] = []

    def pipeline(self, transaction: bool = False) -> Self:
        return self

    def type(self, key: str) -> None:
        self.calls.append(("type", key))

    def ttl(self, key: str) -> None:
        self.calls.append(("ttl", key))

    def memory_usage(self, key: str) -> None:
        self.calls.append(("memory", key))

    def object(self, sub: str, key: str) -> None:
        self.calls.append(("idle", key))

    async def execute(self, raise_on_error: bool = True) -> list[Any]:
        answers = {"type": b"zset", "ttl": 60, "memory": 100}
        return [
            self.idle[key] if op == "idle" else answers[op] for op, key in self.calls
        ]


def test_the_shared_cache_claims_its_database_after_traffic() -> None:
    """The cache's entries have no family of their own (their names are
    whatever services choose), so the cache claims the rest of its
    database; traffic's counters, declared first, keep theirs."""
    from app.services.system import redis_keys

    cache_db = [f for f in redis_keys.families() if f.db == "CACHE_REDIS_DB"]
    names = [f.name for f in cache_db]
    assert names[-1] == "Shared cache" and cache_db[-1].pattern == "*"
    groups, unclaimed = redis_keys.group_keys(
        cache_db, ["insights:project:7", "traffic:total:2026-09-28"]
    )
    claimed = {cache_db[i].name: keys for i, keys in groups.items()}
    assert claimed["Shared cache"] == ["insights:project:7"]
    assert unclaimed == []
    assert "Shared cache" not in [
        cache_db[i].name
        for i, keys in groups.items()
        if "traffic:total:2026-09-28" in keys
    ]


class TestFamilyOf:
    """A key named for what it is: the family that claims it, as the map
    sorts it."""

    def test_a_key_is_named_by_the_family_that_claims_it(self) -> None:
        found = redis_keys.family_of("traffic:sources:2026-10-15T18")
        assert found is not None and found.name == "Traffic sources"
        assert redis_keys.family_of(None) is None

    def test_the_live_charts_history_is_its_own(self) -> None:
        """Not the shared cache's catch-all: the charts' points, their
        tiers and the samplers' own keys say what they are."""
        keys = [
            "series-hour:containers:worker:app-worker-1:cpu",
            "series-60:containers:worker:app-worker-1:cpu",
            "series-index-hour:containers",
            "series-index-60:containers",
            "series-latest:containers",
        ]
        names = [getattr(redis_keys.family_of(k), "name", None) for k in keys]
        assert None not in names and "Shared cache" not in names


def test_every_module_declaring_keys_is_an_owner() -> None:
    """A module's ``REDIS_KEYS`` count only once ``OWNERS`` lists it; one
    left off has its keys fall to the shared cache's catch-all."""
    root = Path(app.__file__).parent.parent
    declaring = {
        ".".join(path.relative_to(root).with_suffix("").parts)
        for path in (root / "app").rglob("*.py")
        if "\nREDIS_KEYS = " in path.read_text()
    }
    assert declaring and declaring <= set(redis_keys.OWNERS)


class TestKeysOf:
    @pytest.mark.asyncio
    async def test_redis_says_which_arguments_are_keys(self) -> None:
        """``COMMAND GETKEYS``: streams, scripts and a slow log's cut
        arguments alike; a command without keys has none."""
        commands = [["ZADD", "k", "1", "m"], ["PING"], []]
        assert await redis_keys.keys_of(SharedRedis(), commands) == [["k"], [], []]


class TestHomes:
    @pytest.mark.asyncio
    async def test_a_key_is_found_in_the_database_that_holds_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The app's database or the cache's; a key gone since has none."""
        # A Redis stack's two databases, whatever stack runs this.
        monkeypatch.setattr(
            redis_keys, "settings", SimpleNamespace(REDIS_DB=0, CACHE_REDIS_DB=1)
        )
        app, cache = SharedRedis(), SharedRedis()
        app.strings["legacy:thing"] = "x"
        cache.strings["insights:project:7"] = "y"
        monkeypatch.setattr(
            redis_keys, "redis_client", lambda db=0: {0: app, 1: cache}[db]
        )
        keys = ["legacy:thing", "insights:project:7", "gone"]
        assert await redis_keys.homes(keys) == {
            "legacy:thing": 0,
            "insights:project:7": 1,
        }
