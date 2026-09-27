"""The Overseer Server page: six tabs carried over from the Flet backend modal."""

from collections.abc import Generator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_server
from app.services.system.models import ComponentStatus
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
            "Load Tests",
            "Routes",
            "Lifecycle",
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

    def test_status_dot_follows_the_live_sidebar_event(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in)
        sidebar_dot = one(html, '#overseer-sidebar a[aria-current="page"] [sse-swap]')
        subnav_dot = one(html, "#overseer-subnav [sse-swap]")
        assert subnav_dot.get("sse-swap") == sidebar_dot.get("sse-swap")

    def test_unknown_section_is_404(self, signed_in: TestClient) -> None:
        assert signed_in.get("/overseer/components/backend/nope").status_code == 404

    def test_sections_need_a_signed_in_user(self, client: TestClient) -> None:
        response = client.get(
            "/overseer/components/backend/routes", follow_redirects=False
        )
        assert response.status_code == 303


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


class TestLoadTests:
    def test_lists_recent_runs(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def runs(**_: Any) -> list[dict[str, Any]]:
            return [
                {
                    "test_id": "t1",
                    "configuration": {"method": "GET", "path": "/health"},
                    "metrics": {
                        "overall_throughput": 250.0,
                        "latency_ms_p95": 4.2,
                        "latency_ms_max": 12.0,
                        "status_codes": {"200": 98, "500": 2},
                        "errors": [
                            {
                                "request_index": i,
                                "error_type": "HTTP500",
                                "message": "boom",
                            }
                            for i in range(7)
                        ],
                    },
                }
            ]

        monkeypatch.setattr(overseer_server, "list_recent_runs", runs)
        html = _get(signed_in, "load-tests")
        assert (
            text(one(html, "tbody tr:not([data-detail])").cssselect("td")[2])
            == "/health"
        )
        detail = text(one(html, "tr[data-detail]"))
        assert "200: 98, 500: 2" in detail
        assert "12.0" in detail
        assert "Error samples (7)" in detail
        assert detail.count("HTTP500") == 5
        assert "and 2 more" in detail

    def test_store_failure_renders_a_notice(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def broken(**_: Any) -> list[dict[str, Any]]:
            raise ConnectionError("redis down")

        monkeypatch.setattr(overseer_server, "list_recent_runs", broken)
        one(_get(signed_in, "load-tests"), "[data-empty]")
