"""The Overseer Redis page: the Flet redis modal's tabs, led by a keyspace map
that says what each part of Redis is for."""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_redis
from app.services.system import redis_keys
from app.services.system.models import ComponentStatus
from app.services.system.ui import get_component_title
from tests.web.dom import none, one, select, text
from tests.web.overseer import sign_in, status_with

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
        {"id": 1, "timestamp": 1_700_000_000, "duration_ms": 12.5, "command": "GET a"},
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

KEYSPACE: dict[str, Any] = {
    "families": [
        {
            "id": 0,
            "name": "Traffic sources",
            "pattern": "traffic:sources:*",
            "kind": "zset",
            "purpose": "Requests per client IP, one sorted set per hour",
            "owner": "Backend traffic monitor",
            "db": 1,
            "count": 2,
            "memory": 2048,
            "ttl": 86400,
            "idle": 1,
            "active": True,
            "latest": "traffic:sources:497354",
        },
        {
            "id": 1,
            "name": "Health probes",
            "pattern": "health_check:*",
            "kind": "string",
            "purpose": "Set/get probe keys the health check writes and deletes",
            "owner": "System health",
            "db": 0,
            "count": 0,
            "memory": 0,
            "ttl": None,
            "idle": None,
            "active": False,
            "latest": None,
        },
    ],
    "unclaimed": {"count": 1, "samples": ["legacy:thing"]},
    "cells": [0, 0, "unclaimed"] + [None] * 39,
    "total": 3,
    "estimated": False,
}

PEEK: dict[str, Any] = {
    "key": "traffic:sources:497354",
    "columns": ["Source IP", "Requests"],
    "rows": [["172.18.0.1", "41"], ["10.0.0.9", "3"]],
}


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    cache = ComponentStatus(name="cache", message="Redis is healthy", metadata=METADATA)
    sign_in(app, monkeypatch, status_with(cache))

    async def keyspace() -> dict[str, Any]:
        return KEYSPACE

    async def peek(family: int) -> dict[str, Any] | None:
        return PEEK if family == 0 else None

    monkeypatch.setattr(overseer_redis, "load_keyspace", keyspace)
    monkeypatch.setattr(overseer_redis, "load_peek", peek)
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
        assert len(cells) == len(KEYSPACE["cells"])
        assert [c.get("data-family") for c in cells[:3]] == ["0", "0", "unclaimed"]
        assert cells[0].get("data-active") == "true"

    def test_the_legend_says_what_each_family_is_for(
        self, signed_in: TestClient
    ) -> None:
        rows = select(_get(signed_in), "#redis-keyspace [data-legend]")
        first = text(rows[0])
        assert "Traffic sources" in first and "traffic:sources:*" in first
        assert "zset" in first
        assert "no keys yet" in text(rows[1])
        assert "Unclaimed" in text(rows[2])

    def test_a_crowded_grid_says_what_a_cell_stands_for(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def crowded() -> dict[str, Any]:
            return KEYSPACE | {"total": 2328}

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
        async def empty() -> dict[str, Any]:
            return {
                "families": [],
                "unclaimed": {"count": 0, "samples": []},
                "cells": [None] * 42,
                "total": 0,
                "estimated": False,
            }

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

    def test_unknown_family_is_404(self, signed_in: TestClient) -> None:
        assert signed_in.get(f"{overseer_redis.PARTIALS}/family/9").status_code == 404

    def test_needs_a_signed_in_user(self, client: TestClient) -> None:
        assert client.get(f"{overseer_redis.PARTIALS}/family/0").status_code == 401


class TestKeyspaceStream:
    @pytest.mark.asyncio
    async def test_sends_the_card_only_when_it_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def keyspace() -> dict[str, Any]:
            return KEYSPACE

        monkeypatch.setattr(overseer_redis, "load_keyspace", keyspace)
        monkeypatch.setattr(overseer_redis, "KEYSPACE_INTERVAL_SECONDS", 0)
        stream = overseer_redis.keyspace_events(max_frames=3)
        frames = [frame async for frame in stream]
        events = [f for f in frames if f.startswith("event:")]
        assert len(events) == 1  # unchanged frames are not re-sent
        assert events[0].startswith(f"event: {overseer_redis.KEYSPACE_EVENT}\n")

    def test_needs_a_signed_in_user(self, client: TestClient) -> None:
        assert client.get(overseer_redis.KEYSPACE_EVENTS).status_code == 401


class TestSlowQueries:
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

        async def read(cells: int = 42) -> dict[str, Any]:
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
        async def down(cells: int = 42) -> dict[str, Any]:
            raise ConnectionError("Redis is not answering")

        monkeypatch.setattr(redis_keys, "read_keyspace", down)
        found = await overseer_redis.load_keyspace()
        assert found["error"] == "Redis is not answering" and found["families"] == []
