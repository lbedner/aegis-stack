"""The backend patterns, detected from the running app.

Each pattern names its rules with the reason behind them; the enforced
ones must hold for every instance in the shipped app.
"""

from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
import pytest

from app.services.system import patterns
from app.services.system.patterns import ROUTE


def _app_with(path: str, **route: object) -> FastAPI:
    """An app with one route whose handler lives in this test module."""
    app = FastAPI()

    async def handler() -> Response:
        """A handler outside the API package."""
        return Response()

    app.add_api_route(path, handler, **route)  # type: ignore[arg-type]
    return app


def _findings(app: FastAPI) -> dict[str, list[str]]:
    report = patterns.report(ROUTE, app.routes)
    return {rule.key: [i.label for i in rule.violations] for rule in report.rules}


class TestRouteRules:
    def test_every_rule_says_why(self) -> None:
        assert all(rule.why for rule in ROUTE.rules)

    def test_the_shipped_app_breaks_no_enforced_rule(self, app: FastAPI) -> None:
        report = patterns.report(ROUTE, app.routes)
        broken = {r.key: [i.label for i in r.violations] for r in report.enforced}
        assert not any(broken.values()), broken

    def test_a_route_published_from_outside_the_api_is_flagged(self) -> None:
        findings = _findings(_app_with("/partials/thing"))
        assert findings["api-package"] == ["GET /partials/thing"]
        assert findings["versioned"] == ["GET /partials/thing"]
        assert findings["tagged"] == ["GET /partials/thing"]

    def test_routes_kept_out_of_the_schema_are_not_instances(self) -> None:
        report = patterns.report(
            ROUTE, _app_with("/page", include_in_schema=False).routes
        )
        assert report.instances == []

    @pytest.mark.parametrize(
        "route",
        [
            {"status_code": 204},
            {"response_class": StreamingResponse},
        ],
    )
    def test_no_content_and_streams_need_no_response_model(
        self, route: dict[str, object]
    ) -> None:
        assert _findings(_app_with("/api/v1/x", **route))["typed"] == []


class TestThinHandler:
    def test_a_handler_doing_its_own_work_is_flagged(self) -> None:
        app = FastAPI()

        async def busy(limit: int = 50) -> dict[str, int]:
            """Validates and computes by hand."""
            limit = min(limit, 200)
            total = sum(range(limit))
            return {"total": total}

        app.add_api_route("/api/v1/busy", busy, tags=["x"])
        assert _findings(app)["thin"] == ["GET /api/v1/busy"]

    def test_a_one_statement_handler_is_thin(self) -> None:
        assert _findings(_app_with("/api/v1/x", tags=["x"]))["thin"] == []

    def test_a_handler_handed_a_service_passes(self) -> None:
        from app.services.system.health import get_system_status

        app = FastAPI()

        async def status() -> dict[str, bool]:
            """Delegates to a service."""
            return {"ok": bool(await get_system_status())}

        app.add_api_route("/api/v1/status", status, tags=["x"], response_model=None)
        assert _findings(app)["thin"] == []


class TestDiagram:
    def test_bars_count_only_the_routes_a_step_applies_to(self, app: FastAPI) -> None:
        report = patterns.report(ROUTE, app.routes)
        assert [s.label for s in report.steps][0] == "Request"
        for step in report.steps:
            if step.followed is not None:
                assert 0 <= step.followed <= step.applicable <= len(report.instances)

    def test_the_service_stage_is_measured(self, app: FastAPI) -> None:
        report = patterns.report(ROUTE, app.routes)
        (service,) = [s for s in report.steps if s.label == "Service"]
        assert service.followed is not None

    def test_the_canonical_example_follows_every_rule_and_stage(
        self, app: FastAPI
    ) -> None:
        report = patterns.report(ROUTE, app.routes)
        assert report.canonical is not None
        assert report.canonical.findings == []
        route = report.canonical.target
        for step in ROUTE.steps:
            if step.follows and (step.applies is None or step.applies(route)):
                assert step.follows(route), step.label
