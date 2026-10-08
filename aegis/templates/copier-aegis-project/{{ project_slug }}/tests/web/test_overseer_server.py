"""The Overseer Server page: six tabs carried over from the Flet backend modal."""

import asyncio
from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_connections, overseer_server
from app.services.system import ui_runtime
from app.services.system.models import ComponentStatus
from tests._fake_runtime import SERVER, FakeRuntime, use_runtime
from tests.web.dom import none, one, select, text
from tests.web.overseer import sign_in, status_with

ROUTES = [
    {
        "path": "/api/v1/items",
        "methods": ["GET"],
        "tags": ["items"],
        "summary": "List items",
        "name": "list_items",
        "requires_auth": True,
        "dependencies": ["get_current_user"],
    },
    {
        "path": "/api/v1/items/{item_id}",
        "methods": ["DELETE"],
        "tags": ["items"],
        "path_params": ["item_id"],
        "deprecated": True,
    },
    {"path": "/health/", "methods": ["GET"], "tags": []},
]

METADATA: dict[str, Any] = {
    "routes": ROUTES,
    "total_routes": 3,
    "total_endpoints": 3,
    "total_middleware": 2,
    "security_count": 1,
    "method_counts": {"GET": 2, "DELETE": 1},
    "middleware_stack": [
        {
            "type": "CORSMiddleware",
            "module": "starlette.middleware.cors",
            "is_security": True,
            "config": {"allow_origins": ["*"]},
        },
    ],
    "lifecycle": {
        "startup_hooks": [
            {
                "name": "database_init",
                "module": "app.startup.db",
                "description": "Open the pool",
            }
        ],
        "shutdown_hooks": [],
    },
}


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    backend = ComponentStatus(name="backend", message="Serving", metadata=METADATA)
    sign_in(app, monkeypatch, status_with(backend))
    with TestClient(app) as test_client:
        yield test_client


def _get(client: TestClient, tab: str = "") -> str:
    url = "/overseer/components/backend" + (f"/{tab}" if tab else "")
    response = client.get(url)
    assert response.status_code == 200
    return response.text


class TestSections:
    def test_sub_menu_groups_sections_with_overview_first(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in)
        subnav = one(html, "#overseer-subnav")
        assert text(one(subnav, "h2")) == "Server"
        assert [text(h) for h in select(subnav, "h3")] == ["Monitoring", "Application"]
        assert [text(a) for a in select(subnav, "nav a")] == [
            "Overview",
            "Performance",
            "Traffic",
            "Cache",
            "Connections",
            "Load Tests",
            "Routes",
            "Lifecycle",
            "Container",
            "Logs",
            "Settings",
        ]
        assert text(one(subnav, 'a[aria-current="page"]')) == "Overview"
        none(html, '[role="tablist"]')

    def test_current_section_titles_the_page(self, signed_in: TestClient) -> None:
        html = _get(signed_in, "routes")
        assert text(one(html, "h1")) == "Routes"
        assert text(one(html, '#overseer-subnav a[aria-current="page"]')) == "Routes"

    def test_links_swap_the_sub_menu_and_content_and_keep_the_sidebar(
        self, signed_in: TestClient
    ) -> None:
        link = one(_get(signed_in), '#overseer-subnav a[href$="/routes"]')
        assert link.get("hx-target") == "#overseer-main"
        assert link.get("hx-select") == "#overseer-main"
        html = _get(signed_in, "routes")
        one(html, "#overseer-sidebar")
        one(html, "#overseer-main #overseer-subnav")

    def test_the_sidebar_is_never_swapped_so_it_keeps_its_scroll(
        self, signed_in: TestClient
    ) -> None:
        """A sidebar link replaces only what is right of it; app.js moves
        the sidebar's current mark (``markCurrent``)."""
        links = select(_get(signed_in), "#overseer-sidebar a[hx-get]")
        assert links
        assert {(a.get("hx-target"), a.get("hx-select")) for a in links} == {
            ("#overseer-main", "#overseer-main")
        }

    def test_status_dot_follows_the_live_sidebar_event(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in)
        sidebar_dot = one(html, '#overseer-sidebar a[aria-current="page"] [sse-swap]')
        subnav_dot = one(html, "#overseer-subnav [sse-swap]")
        assert subnav_dot.get("sse-swap") == sidebar_dot.get("sse-swap")

    def test_unknown_section_is_404(self, signed_in: TestClient) -> None:
        assert signed_in.get("/overseer/components/backend/nope").status_code == 404


class TestOverview:
    def test_shows_api_figures_and_methods(self, signed_in: TestClient) -> None:
        html = _get(signed_in)
        figures = {
            text(cell.getparent().cssselect("dt")[0]): text(cell)
            for cell in select(html, "#server-api dd:first-of-type")
        }
        assert figures["Routes"] == "3"
        assert figures["Middleware"] == "2"
        assert "2 GET" in text(one(html, "#card-current-status"))
        # Every route one method: endpoints would repeat the routes.
        assert "Endpoints" not in figures

    def test_endpoints_show_when_a_route_has_more_than_one_method(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = ComponentStatus(
            name="backend",
            message="Serving",
            metadata=METADATA | {"total_endpoints": 5},
        )
        sign_in(app, monkeypatch, status_with(backend))
        html = _get(TestClient(app))
        labels = [text(dt) for dt in select(html, "#server-api dt")]
        assert "Endpoints" in labels

    def test_its_figures_are_its_containers_not_the_hosts(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The host's are on Resources; the Server shows what its own
        container uses, live, like every page with one."""
        use_runtime(monkeypatch, FakeRuntime(SERVER))
        asyncio.run(ui_runtime.containers("server"))
        html = _get(signed_in)
        one(html, f'#runtime-glance [data-glance="{SERVER.name}"]')
        none(html, "#card-resources")

    def test_without_a_container_it_shows_the_machine_it_runs_on(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        use_runtime(monkeypatch, FakeRuntime(SERVER, backend_name="none"))
        one(_get(signed_in), "#card-resources")


class TestRoutes:
    def test_groups_by_first_tag_with_untagged_last(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in, "routes")
        groups = [
            text(one(g, "summary h2"))
            for g in select(html, "details[data-route-group]")
        ]
        assert groups == ["items", "Untagged"]

    def test_row_marks_auth_and_deprecation(self, signed_in: TestClient) -> None:
        html = _get(signed_in, "routes")
        rows = {
            text(row.cssselect("td")[2]): row
            for row in select(html, "tbody tr:not([data-detail])")
        }
        assert "Auth" in text(rows["/api/v1/items"])
        assert "Auth" not in text(rows["/health/"])
        assert "Deprecated" in text(rows["/api/v1/items/{item_id}"])
        assert text(one(rows["/api/v1/items"], "[data-method]")) == "GET"
        assert "get_current_user" in text(select(html, "tr[data-detail]")[0])

    def test_methods_render_the_same_on_every_table(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            overseer_server.metrics_service,
            "get_summary_stats",
            lambda: {"total_requests": 1, "tracked_endpoints": 1},
        )
        monkeypatch.setattr(
            overseer_server.metrics_service,
            "get_all_metrics",
            lambda: {"POST /b": {"count": 1}},
        )
        html = _get(signed_in, "performance")
        assert text(one(html, "tbody [data-method]")) == "POST"


class TestPerformance:
    def test_lists_endpoints_busiest_first(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            overseer_server.metrics_service,
            "get_summary_stats",
            lambda: {
                "total_requests": 12,
                "tracked_endpoints": 2,
                "avg_ms": 3.0,
                "p95_ms": 9.0,
            },
        )
        monkeypatch.setattr(
            overseer_server.metrics_service,
            "get_all_metrics",
            lambda: {
                "GET /a": {"count": 2, "avg_ms": 1.0},
                "POST /b": {"count": 10, "avg_ms": 5.0},
            },
        )
        html = _get(signed_in, "performance")
        paths = [
            text(row.cssselect("td")[2])
            for row in select(html, "tbody tr:not([data-detail])")
        ]
        assert paths == ["/b", "/a"]
        assert "Min ms" in text(select(html, "tr[data-detail]")[0])

    def test_empty_until_requests_arrive(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            overseer_server.metrics_service,
            "get_summary_stats",
            lambda: {"total_requests": 0},
        )
        monkeypatch.setattr(
            overseer_server.metrics_service, "get_all_metrics", lambda: {}
        )
        one(_get(signed_in, "performance"), "[data-empty]")


class TestTraffic:
    def test_flags_a_dominant_source(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def sources(**_: Any) -> dict[str, Any]:
            return {
                "total_requests": 100,
                "window_hours": 24,
                "backend": "memory",
                "sources": [{"ip": "10.0.0.9", "requests": 90, "share": 0.9}],
                "dominant": {"ip": "10.0.0.9", "requests": 90, "share": 0.9},
            }

        monkeypatch.setattr(overseer_server, "get_traffic_sources", sources)
        html = _get(signed_in, "traffic")
        assert "10.0.0.9" in text(one(html, '[role="alert"]'))
        assert (
            text(one(html, "tbody tr:not([data-detail]) td:nth-child(2)")) == "10.0.0.9"
        )


class TestLifecycle:
    def test_shows_hooks_and_middleware(self, signed_in: TestClient) -> None:
        html = _get(signed_in, "lifecycle")
        assert "database_init" in text(one(html, "#lifecycle-startup"))
        middleware = one(html, "#lifecycle-middleware")
        assert "CORSMiddleware" in text(middleware)
        assert "Security" in text(middleware)
        one(html, "#lifecycle-shutdown [data-empty]")


class TestCache:
    """What is in the cache, by family: how much room each takes and
    whether it earns it."""

    def _view(self) -> dict[str, Any]:
        from app.core.cache import CacheEntry, CacheStats
        from app.services.system import ui_cache

        return {"error": None} | ui_cache.summarize(
            "redis",
            [
                CacheEntry("insights:project:1", 4000, 200),
                CacheEntry("llm:price:gpt-4o", 100, 50),
            ],
            False,
            {"insights:project": CacheStats(hits=3, misses=1, sets=1)},
        )

    def _serve(self, monkeypatch: pytest.MonkeyPatch, view: dict[str, Any]) -> None:
        from app.services.system import ui_cache

        async def load() -> dict[str, Any]:
            return view

        monkeypatch.setattr(ui_cache, "load", load)

    def test_families_rank_by_room_with_hit_rates(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch, self._view())
        rows = select(_get(signed_in, "cache"), "#cache-families tbody tr")
        assert text(select(rows[0], "td")[0]) == "insights:project"
        assert "75.0%" in text(rows[0])

    def test_the_largest_keys_are_listed(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch, self._view())
        first = select(_get(signed_in, "cache"), "#cache-largest tbody tr")[0]
        assert "insights:project:1" in text(first)

    def test_an_unreadable_cache_says_why(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch, {"error": "redis down", "backend": "redis"})
        assert "redis down" in text(one(_get(signed_in, "cache"), "[role=alert]"))


class TestConnections:
    """Every WebSocket and event stream, open and recently closed: where it
    goes, who holds it, its state, and a timeline in the drawer. The table
    refreshes itself while the page is open."""

    PAGE = "/overseer/components/backend/connections"

    def _records(self) -> list[dict[str, Any]]:
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)

        def record(
            rid: str, kind: str, path: str, state: str, **extra: Any
        ) -> dict[str, Any]:
            return {
                "id": rid,
                "kind": kind,
                "path": path,
                "client": "172.18.0.1",
                "agent": "Firefox",
                "first_opened": now - timedelta(hours=2),
                "opened_at": now - timedelta(minutes=5),
                "closed_at": None if state == "up" else now - timedelta(minutes=1),
                "state": state,
                "ended": None if state == "up" else "client went away",
                "reconnects": 0,
                "sent": 40,
                "received": 12,
                "events": [(now - timedelta(hours=2), "connected", None)],
            } | extra

        return [
            record(
                "ws1",
                "websocket",
                "/dashboard/ws",
                "up",
                reconnects=2,
                events=[
                    (now - timedelta(hours=2), "connected", None),
                    (now - timedelta(hours=1), "dropped", "client went away"),
                    (now - timedelta(hours=1), "reconnected", "after 3s"),
                ],
            ),
            record("sse1", "sse", "/overseer/events", "reconnecting"),
            record("sse2", "sse", "/api/v1/jobs/events", "closed"),
        ]

    def _serve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        records = self._records()

        async def history() -> list[dict[str, Any]]:
            return records

        async def find(rid: str) -> dict[str, Any] | None:
            return next((r for r in records if r["id"] == rid), None)

        monkeypatch.setattr(overseer_connections, "history", history)
        monkeypatch.setattr(overseer_connections, "find", find)

    def _paths(self, html: str) -> list[str]:
        return [
            text(select(r, "td")[1])
            for r in select(html, "#server-connections tbody tr")
        ]

    def test_open_is_the_default_and_counts_reconnecting(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch)
        assert self._paths(_get(signed_in, "connections")) == [
            "/dashboard/ws",
            "/overseer/events",
        ]

    def test_the_filters_narrow_by_state_and_kind(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch)
        closed = signed_in.get(f"{self.PAGE}?state=closed").text
        assert self._paths(closed) == ["/api/v1/jobs/events"]
        sockets = signed_in.get(f"{self.PAGE}?state=all&kind=websocket").text
        assert self._paths(sockets) == ["/dashboard/ws"]

    def test_a_row_shows_its_state_and_reconnects(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch)
        first = select(_get(signed_in, "connections"), "#server-connections tbody tr")[
            0
        ]
        assert "Up" in text(first) and "WebSocket" in text(first)
        assert text(select(first, "td")[4]) == "2"

    def test_the_figures_count_each_state(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch)
        figures = {
            text(one(cell, "dt")): text(select(cell, "dd")[0])
            for cell in select(
                _get(signed_in, "connections"), "#connection-figures > div"
            )
        }
        assert (figures["Up"], figures["Reconnecting"], figures["Closed"]) == (
            "1",
            "1",
            "1",
        )

    def test_a_connection_opens_its_timeline_in_the_drawer(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch)
        link = one(
            select(_get(signed_in, "connections"), "#server-connections tbody tr")[0],
            "a",
        )
        assert "connection=ws1" in link.get("href")
        drawer = signed_in.get("/partials/overseer/server/connections/ws1/drawer")
        assert drawer.status_code == 200, drawer.text
        steps = [text(li) for li in select(drawer.text, "#connection-timeline li")]
        assert len(steps) == 3 and "reconnected" in steps[2] and "after 3s" in steps[2]

    def test_the_table_refreshes_itself_with_its_filters(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch)
        live = one(signed_in.get(f"{self.PAGE}?state=closed").text, "#connections-live")
        assert live.get("sse-connect").startswith(overseer_connections.EVENTS)
        assert "state=closed" in live.get("sse-connect")

    async def test_a_frame_is_the_filtered_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch)
        [frame] = [
            f
            async for f in overseer_connections.connections_events(
                {"state": "closed"}, max_frames=1
            )
        ]
        assert frame.startswith(f"event: {overseer_connections.EVENT}")
        assert "/api/v1/jobs/events" in frame and "/dashboard/ws" not in frame

    def test_nothing_remembered_says_so(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def history() -> list[dict[str, Any]]:
            return []

        monkeypatch.setattr(overseer_connections, "history", history)
        one(_get(signed_in, "connections"), "[data-empty]")
