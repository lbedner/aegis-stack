"""The Overseer Redis page: the Flet redis modal's tabs, led by a keyspace map
that says what each part of Redis is for."""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_redis
from app.core.key_family import KeyFamily
from app.services.system import redis_facts, redis_keys
from app.services.system.models import (
    ComponentStatus,
    FamilyDetail,
    KeyFamilyRow,
    Keyspace,
    Unclaimed,
)
from app.services.system.ui import get_component_title
from tests.web.dom import none, one, select, text
from tests.web.overseer import sent_events, sign_in, status_with

METADATA: dict[str, Any] = {
    "implementation": "redis",
    "version": "7.2.4",
    "url": "redis://:secret@redis:6379",
    "connected_clients": 3,
    "blocked_clients": 0,
    "total_connections_received": 41,
    "uptime_in_seconds": 90061,
    "used_memory_human": "1.2M",
    "used_memory_peak_human": "2.0M",
    "maxmemory_human": "0B",
    "mem_fragmentation_ratio": 1.5,
    "instantaneous_ops_per_sec": 12,
    "hit_rate_percent": 95.5,
    "total_keys": 3,
    "slowlog_entries": [
        {
            "id": 1,
            "timestamp": 1_700_000_000,
            "duration_ms": 12.5,
            "command": "ZSCORE traffic:sources:1 10.0.0.1",
            "keys": ["traffic:sources:1"],
        },
        {
            "id": 2,
            "timestamp": 1_700_000_100,
            "duration_ms": 1500.0,
            "command": "KEYS *",
        },
    ],
    "active_clients": [
        {
            "id": "7",
            "addr": "172.18.0.4:5000",
            "age": "30",
            "idle": "0",
            "db": "1",
            "cmd": "zincrby",
        },
    ],
}

TRAFFIC = KeyFamily(
    "traffic:sources:*",
    "zset",
    "Traffic sources",
    "Requests per client IP, one sorted set per hour",
    "Backend traffic monitor",
    db="CACHE_REDIS_DB",
    columns=("Source IP", "Requests"),
)
PROBES = KeyFamily(
    "health_check:*",
    "string",
    "Health probes",
    "Set/get probe keys the health check writes and deletes",
    "System health",
)
KEYSPACE = Keyspace(
    families=[
        KeyFamilyRow(
            family=TRAFFIC,
            id=0,
            db=1,
            count=2,
            memory=2048,
            ttl=86400,
            idle=1,
            active=True,
            latest="traffic:sources:497354",
        ),
        KeyFamilyRow(family=PROBES, id=1, db=0),
    ],
    unclaimed=Unclaimed(count=1, samples=["legacy:thing"]),
    cells=[0, 0, "unclaimed"] + [None] * 39,
    total=3,
)

DETAIL = FamilyDetail.model_validate(
    {
        "key": "traffic:sources:497354",
        "columns": ["Source IP", "Requests"],
        "rows": [
            {"a": "172.18.0.1", "b": "41", "when": None},
            {"a": "10.0.0.9", "b": "3", "when": None},
        ],
        "facts": {
            "figures": [("Held now", "2 sources")],
            "spark": None,
            "groups": [],
            "partial": 0,
        },
    }
)
STREAM_DETAIL = FamilyDetail.model_validate(
    {
        "key": "aegis:events:worker",
        "columns": ["Entry", "Event"],
        "rows": [
            {
                "a": "1800000000000-0",
                "b": "event_type=job.completed · queue=system",
                "when": "20s ago",
            }
        ],
        "facts": {
            "figures": [("Through it", "41,203 events"), ("Last minute", "12")],
            "spark": "0.0,24.0 100.0,0.0",
            "groups": [
                {"name": "overseer", "consumers": 1, "pending": 2, "lag": "caught up"}
            ],
            "partial": 50,
        },
    }
)


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    cache = ComponentStatus(name="cache", message="Redis is healthy", metadata=METADATA)
    sign_in(app, monkeypatch, status_with(cache))

    async def keyspace() -> Keyspace:
        return KEYSPACE

    async def detail(family: int, latest: str | None = None) -> FamilyDetail | None:
        return {0: DETAIL, 1: STREAM_DETAIL}.get(family)

    monkeypatch.setattr(overseer_redis, "load_keyspace", keyspace)
    monkeypatch.setattr(redis_facts, "detail", detail)
    with TestClient(app) as client:
        yield client


def _get(client: TestClient, section: str = "") -> str:
    url = "/overseer/components/cache" + (f"/{section}" if section else "")
    response = client.get(url)
    assert response.status_code == 200
    return response.text


class TestSections:
    def test_overview_then_activity(self, signed_in: TestClient) -> None:
        subnav = one(_get(signed_in), "#overseer-subnav")
        assert text(one(subnav, "h2")) == get_component_title("cache")
        assert [text(a) for a in select(subnav, "nav a")] == [
            "Overview",
            "Slow queries",
            "Connections",
            "Container",
            "Logs",
        ]


class TestOverview:
    def test_the_flet_figures_lead(self, signed_in: TestClient) -> None:
        strip = text(one(_get(signed_in), "#redis-figures"))
        for figure in ("1.2M", "12", "95.5%", "3", "1d 1h 1m"):
            assert figure in strip

    def test_the_keyspace_streams_itself(self, signed_in: TestClient) -> None:
        """Pushed over SSE while the page is open; the browser never polls."""
        card = one(_get(signed_in), "#redis-keyspace")
        assert card.get("sse-connect") == overseer_redis.KEYSPACE_EVENTS
        assert one(card, "[sse-swap]").get("sse-swap") == overseer_redis.KEYSPACE_EVENT
        assert card.get("hx-trigger") is None

    def test_a_cell_per_key_coloured_by_family(self, signed_in: TestClient) -> None:
        html = _get(signed_in)
        cells = select(html, "#redis-keyspace .keyspace__cell")
        assert len(cells) == len(KEYSPACE.cells)
        assert [c.get("data-family") for c in cells[:3]] == ["0", "0", "unclaimed"]
        assert cells[0].get("data-active") == "true"

    def test_the_legend_says_what_each_family_is_for(
        self, signed_in: TestClient
    ) -> None:
        rows = select(_get(signed_in), "#redis-keyspace [data-legend]")
        first = text(rows[0])
        assert "Traffic sources" in first
        assert "Requests per client IP, one sorted set per hour" in first
        assert "no keys yet" in text(rows[1])
        assert "Unclaimed" in text(rows[2])

    def test_a_crowded_grid_says_what_a_cell_stands_for(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def crowded() -> Keyspace:
            return KEYSPACE.model_copy(update={"total": 2328})

        monkeypatch.setattr(overseer_redis, "load_keyspace", crowded)
        assert "1 cell ≈ 55 keys" in text(one(_get(signed_in), "#redis-keyspace"))

    def test_a_sparse_grid_is_a_cell_per_key(self, signed_in: TestClient) -> None:
        assert "1 cell ≈" not in text(one(_get(signed_in), "#redis-keyspace"))

    def test_picking_a_family_loads_its_detail(self, signed_in: TestClient) -> None:
        row = select(_get(signed_in), "#redis-keyspace [data-legend]")[0]
        assert row.get("hx-get") == f"{overseer_redis.PARTIALS}/family/0"
        assert row.get("hx-target") == "#redis-family"

    def test_an_empty_keyspace_says_so(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def empty() -> Keyspace:
            return Keyspace(cells=[None] * 42)

        monkeypatch.setattr(overseer_redis, "load_keyspace", empty)
        html = _get(signed_in)
        one(html, "#redis-keyspace [data-empty]")
        none(html, "#redis-keyspace [data-legend]")


class TestFamilyDetail:
    def test_reads_the_family_in_its_owners_words(self, signed_in: TestClient) -> None:
        response = signed_in.get(f"{overseer_redis.PARTIALS}/family/0")
        assert response.status_code == 200
        html = response.text
        assert "Requests per client IP" in text(one(html, "[data-purpose]"))
        assert "Backend traffic monitor" in text(
            html_root := one(html, "#redis-family")
        )
        assert [text(th) for th in select(html_root, "thead th")] == [
            "Source IP",
            "Requests",
        ]
        assert "172.18.0.1" in text(one(html_root, "tbody"))

    def test_says_how_much_it_holds_in_its_word(self, signed_in: TestClient) -> None:
        html = signed_in.get(f"{overseer_redis.PARTIALS}/family/0").text
        figures = text(one(html, "#redis-family [data-figures]"))
        assert "Held now" in figures and "2 sources" in figures
        assert "traffic:sources:*" in text(one(html, "#redis-family"))
        none(html, "#redis-family [data-spark]")  # nothing dates a count
        none(html, "#redis-family [data-groups]")

    def test_a_stream_says_what_went_through_and_who_reads_it(
        self, signed_in: TestClient
    ) -> None:
        html = signed_in.get(f"{overseer_redis.PARTIALS}/family/1").text
        root = one(html, "#redis-family")
        figures = text(one(root, "[data-figures]"))
        assert "Through it" in figures and "41,203 events" in figures
        one(root, "[data-spark] svg")
        assert "overseer" in text(one(root, "[data-groups]"))
        assert "caught up" in text(one(root, "[data-groups]"))
        assert "first 50 keys" in text(root)  # more keys than were read
        headers = [text(th) for th in select(root, "[data-newest] thead th")]
        assert headers == ["Entry", "Event", "When"]
        assert "20s ago" in text(one(root, "[data-newest] tbody"))

    def test_unknown_family_is_404(self, signed_in: TestClient) -> None:
        assert signed_in.get(f"{overseer_redis.PARTIALS}/family/9").status_code == 404


class TestKeyspaceStream:
    @pytest.mark.asyncio
    async def test_sends_the_card_only_when_it_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def keyspace() -> Keyspace:
            return KEYSPACE

        monkeypatch.setattr(overseer_redis, "load_keyspace", keyspace)
        monkeypatch.setattr(overseer_redis, "KEYSPACE_INTERVAL_SECONDS", 0)
        events = await sent_events(overseer_redis.keyspace_events(max_frames=3))
        assert len(events) == 1  # unchanged frames are not re-sent
        assert events[0].startswith(f"event: {overseer_redis.KEYSPACE_EVENT}\n")


class TestSlowQueries:
    def test_each_command_names_what_it_touched(self, signed_in: TestClient) -> None:
        """The key's family, as the keyspace map names it, and the key."""
        rows = select(_get(signed_in, "slow-queries"), "tbody tr")
        touched = text(one(rows[1], "[data-family]"))
        assert "Traffic sources" in touched and "traffic:sources:1" in touched
        none(rows[0], "[data-family]")  # KEYS * touches no one key

    def test_slowest_first_and_flagged(self, signed_in: TestClient) -> None:
        rows = select(_get(signed_in, "slow-queries"), "tbody tr")
        assert "KEYS *" in text(rows[0])
        assert one(rows[0], "[data-tone]").get("data-tone") == "error"
        assert "1,500.00ms" in text(rows[0]) or "1500.00ms" in text(rows[0])


class TestConnections:
    def test_facts_and_clients(self, signed_in: TestClient) -> None:
        html = _get(signed_in, "connections")
        facts = text(one(html, "#redis-connection"))
        assert "secret" not in facts
        assert "localhost:6379" in facts
        assert "41" in facts
        row = one(html, "tbody tr")
        assert "172.18.0.4:5000" in text(row) and "zincrby" in text(row)


class TestKeyspaceSampler:
    """The keyspace is a sampler (``app.core.series``): one SCAN a tick for
    every viewer, not one per open stream."""

    @pytest.mark.asyncio
    async def test_every_view_reads_one_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scans = []

        async def read(cells: int = 42) -> Keyspace:
            scans.append(cells)
            return KEYSPACE

        monkeypatch.setattr(redis_keys, "read_keyspace", read)
        first = await overseer_redis.load_keyspace()
        second = await overseer_redis.load_keyspace()
        assert first == second == KEYSPACE and len(scans) == 1

    @pytest.mark.asyncio
    async def test_a_failed_read_is_shown_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def down(cells: int = 42) -> Keyspace:
            raise ConnectionError("Redis is not answering")

        monkeypatch.setattr(redis_keys, "read_keyspace", down)
        found = await overseer_redis.load_keyspace()
        assert found.error == "Redis is not answering" and found.families == []
