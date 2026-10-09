"""Errors navigation, escaped detail, HTMX fragments, the shared Services
picker, and unavailable states."""

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_errors
from app.services.system import ui_errors
from app.services.system.errors.models import ErrorIssue
from app.services.system.models import ComponentStatus
from tests._error_store import occurrence
from tests._fake_runtime import REDIS, STOPPED, WORKER, FakeRuntime, use_runtime
from tests.web.dom import one, select, text
from tests.web.overseer import CACHE, page_html, sign_in, status_with


@pytest.fixture
def errors_client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(
        app,
        monkeypatch,
        status_with(
            CACHE,
            ComponentStatus(name="worker", message=""),
            services=[ComponentStatus(name="auth", message="")],
        ),
    )
    use_runtime(monkeypatch, FakeRuntime(REDIS, WORKER, STOPPED))

    async def load(
        query: Mapping[str, str], part: Any = ui_errors.load_list
    ) -> dict[str, Any]:
        event = occurrence("one").model_copy(
            update={
                "traceback": (
                    "<script>alert(1)</script>\nTraceback (most recent call last):\n"
                    '  File "app.py", line 1, in run\nValueError: bad'
                ),
                "truncated": True,
                "app_service": "ai",
            }
        )
        shown = {"error_status": {"state": "degraded", "reason": "Docker unavailable"}}
        if part is ui_errors.load_detail:
            shown |= {
                "error_detail": event,
                "error_history": [event],
                "error_history_total": 1,
            }
        return ui_errors.DEFAULTS | shown

    monkeypatch.setattr(ui_errors, "load", load)
    return TestClient(app)


def test_sidebar_and_standalone(errors_client: TestClient) -> None:
    assert 'href="/overseer/errors"' in page_html(errors_client, "/overseer?view=map")
    assert "Docker unavailable" in page_html(errors_client, "/overseer/errors")


def test_bookmarkable_detail_escapes_trace(errors_client: TestClient) -> None:
    page = page_html(
        errors_client,
        "/overseer/errors?issue=same&occurrence=one&service=redis&container=app-worker-system-1",
    )
    marker = one(page, "[data-drawer-sync]")
    assert marker.get("data-drawer-param") == "issue"
    assert "service=redis" in marker.get("data-drawer-url")
    assert "container=app-worker-system-1" in marker.get("data-drawer-url")
    assert not select(page, "#error-detail")
    html = page_html(errors_client, marker.get("data-drawer-url"))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "Trace truncated" in html
    # Highlighted as a Python traceback, wrapping like any long block.
    trace = one(html, "#error-detail .code-block--wrap .highlight")
    assert text(one(trace, ".gr")) == "ValueError"
    assert "ValueError: bad" in text(trace)
    facts = [text(dt) for dt in select(html, "#error-detail dl dt")]
    assert "Application service" in facts and "Runtime" in facts


def test_partial_and_filter_state(errors_client: TestClient) -> None:
    html = page_html(errors_client, "/partials/overseer/errors?q=needle")
    assert "errors-results" in html
    full = page_html(errors_client, "/overseer/errors?q=needle&level=critical")
    assert 'value="needle"' in full
    assert 'sse-connect="/overseer/events/errors?' in full


def test_the_services_picker_is_the_logs_one(errors_client: TestClient) -> None:
    """The same checklist as Logs, the same names: a filter carries across."""
    html = page_html(
        errors_client,
        "/overseer/errors?service=redis&container=app-worker-system-1&app_service=auth",
    )
    picks = {
        (o.get("name"), o.get("value")): o.get("checked") is not None
        for o in select(html, "#errors-sources input")
    }
    assert picks[("service", "redis")] and not picks[("service", "worker")]
    assert picks[("container", WORKER.name)] and not picks[("container", STOPPED.name)]
    assert picks[("app_service", "auth")]
    events = one(html, "#errors [sse-connect]").get("sse-connect")
    assert "service=redis" in events and "app_service=auth" in events
    form = one(html, "#errors form")
    assert "change" in (form.get("hx-trigger") or "")
    assert form.get("hx-target") == "#errors"
    assert one(html, "#errors-sources").get("hx-preserve") is not None
    for control in select(html, "#errors select"):
        assert {"select-caret", "pr-8"} <= set(control.get("class").split())


@pytest.mark.parametrize(
    ("container", "page", "runtime"),
    [
        ("app-webserver-1", "server", "Server"),
        (WORKER.name, "worker", "Worker · system"),
    ],
)
def test_a_row_names_its_runtime_as_logs_does(
    container: str, page: str, runtime: str
) -> None:
    issue = ErrorIssue(
        fingerprint="one",
        page=page,
        service="any",
        container_name=container,
        message="boom",
        exception_type="RuntimeError",
        count=1,
        first_seen="2026-10-07T00:00:00Z",
        last_seen="2026-10-07T00:00:00Z",
        latest_id="one",
    )
    context = ui_errors.DEFAULTS | {"error_rows": [issue], "error_total": 1}
    names = {WORKER.name: "Worker · system"}
    source = one(overseer_errors.render(context, {}, names), "tbody td:nth-child(2)")
    assert text(one(source, "span")) == runtime
    assert "Unattributed" in text(source)


@pytest.mark.parametrize(("state", "tone"), [("running", "ok"), ("degraded", "warn")])
def test_the_collector_state_badge_is_toned(state: str, tone: str) -> None:
    html = overseer_errors.render(ui_errors.empty(state, ""), {}, {})
    assert one(html, '[role="status"] [data-tone]').get("data-tone") == tone
