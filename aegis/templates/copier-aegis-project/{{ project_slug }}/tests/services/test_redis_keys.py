"""The Redis keyspace map: which part of the app owns each key, and how the
map draws them."""

from typing import Any

import pytest

from app.services.system import redis_keys
from app.services.system.redis_keys import KeyFamily

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
            "a": {"type": "zset", "ttl": 60, "idle": 2, "bytes": 100},
            "b": {"type": "zset", "ttl": 30, "idle": 50, "bytes": 300},
        }
        summary = redis_keys.summarize(["a", "b", "c"], probes)
        assert summary["count"] == 3
        assert summary["memory"] == 600  # average sample size times the count
        assert summary["idle"] == 2
        assert summary["active"] is True
        assert summary["latest"] == "a"  # the most recently touched

    def test_a_quiet_family_is_not_active(self) -> None:
        probes = {"a": {"type": "zset", "ttl": -1, "idle": 3600, "bytes": 10}}
        assert redis_keys.summarize(["a"], probes)["active"] is False


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
        probes = await redis_keys._probe(FakeRedis(idle), [keys])
        summary = redis_keys.summarize(keys, probes)
        assert summary["active"] is True
        assert summary["latest"] == keys[-1]


class FakeRedis:
    """Just enough of a pipeline: every command answers from ``idle``."""

    def __init__(self, idle: dict[str, int]) -> None:
        self.idle = idle
        self.calls: list[tuple[str, str]] = []

    def pipeline(self, transaction: bool = False) -> FakeRedis:
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
