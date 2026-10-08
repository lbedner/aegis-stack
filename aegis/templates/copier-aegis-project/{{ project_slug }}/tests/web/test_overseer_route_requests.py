"""A route's request form, read from its OpenAPI operation: Routes shows it
under each route to send one request (Execute); Load Tests shows the same
form to send it many times."""

from collections.abc import Generator
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest

from app.components.web_frontend import overseer_requests, overseer_server_load_tests
from app.services.load_test.api import auth
from app.services.system.models import ComponentStatus
from tests.web.dom import none, one, select, text, triggers
from tests.web.overseer import page_html, sign_in, status_with
from tests.web.test_overseer_server_load_tests import FakeRunner

ITEM = "GET /api/v1/try-items/{item_id}"
NEW = "POST /api/v1/try-items"


class NewItem(BaseModel):
    name: str
    price: float = 9.5


@pytest.fixture
def routes(app: FastAPI) -> Generator[None]:
    """Two routes of the app's own for the test, gone after it."""
    before = list(app.router.routes)

    async def read_item(item_id: int, q: str | None = None) -> dict[str, Any]:
        return {"item_id": item_id, "q": q}

    async def create_item(item: NewItem) -> NewItem:
        return item

    app.add_api_route("/api/v1/try-items/{item_id}", read_item, methods=["GET"])
    app.add_api_route("/api/v1/try-items", create_item, methods=["POST"])
    yield
    app.router.routes[:] = before


@pytest.fixture
def signed_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, routes: None
) -> Generator[TestClient]:
    monkeypatch.setattr(auth, "auth_installed", lambda: False)  # no users to make
    listed = [
        {"path": "/api/v1/try-items/{item_id}", "methods": ["GET"], "tags": ["items"]},
        {"path": "/api/v1/try-items", "methods": ["POST"], "tags": ["items"]},
    ]
    backend = ComponentStatus(
        name="backend", message="Serving", metadata={"routes": listed}
    )
    sign_in(app, monkeypatch, status_with(backend))
    with TestClient(app) as client:
        yield client


def _form(client: TestClient, route: str, mode: str = "try", **query: str) -> str:
    url = f"{overseer_requests.PARTIALS}/form?route={quote(route)}&mode={mode}"
    url += "".join(f"&{quote(k)}={quote(v)}" for k, v in query.items())
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.text


class TestTheForm:
    def test_a_parameter_is_a_field_of_its_type(self, signed_in: TestClient) -> None:
        html = _form(signed_in, ITEM)
        item_id = one(html, 'input[name="path.item_id"]')
        assert item_id.get("type") == "number" and item_id.get("required") is not None
        assert one(html, 'input[name="query.q"]').get("required") is None
        none(html, 'input[name="confirm"]')  # a read sends without asking

    def test_a_body_starts_as_an_example_from_its_model(
        self, signed_in: TestClient
    ) -> None:
        html = _form(signed_in, NEW)
        body = text(one(html, 'textarea[name="body"]'))
        assert '"name": "string"' in body and '"price": 9.5' in body
        one(html, 'input[name="confirm"]')  # a write asks first

    def test_load_test_this_takes_the_filled_form_to_load_tests(
        self, signed_in: TestClient
    ) -> None:
        button = next(
            b for b in select(_form(signed_in, ITEM), "button") if "Load test" in text(b)
        )
        assert button.get("hx-get") == overseer_requests.LOAD_TESTS_URL
        assert button.get("hx-include") == "closest form"

    def test_an_unknown_route_is_not_found(self, signed_in: TestClient) -> None:
        url = f"{overseer_requests.PARTIALS}/form?route={quote('GET /nope')}"
        assert signed_in.get(url).status_code == 404

    def test_routes_shows_it_under_each_route(self, signed_in: TestClient) -> None:
        html = page_html(signed_in, "/overseer/components/backend/routes")
        loads = [e.get("hx-get") for e in select(html, "tr[data-detail] [hx-get]")]
        assert any(quote(ITEM) in (url or "") for url in loads)


class TestExecute:
    def test_a_read_is_sent_once_and_its_answer_shown(
        self, signed_in: TestClient
    ) -> None:
        response = signed_in.post(
            f"{overseer_requests.PARTIALS}/execute",
            data={"route": ITEM, "path.item_id": "7", "query.q": "hi"},
        )

        assert response.status_code == 200
        assert one(response.text, "[data-status]").text.strip() == "200"
        assert '"item_id": 7' in text(one(response.text, "[data-body] pre"))
        assert "curl -X GET" in text(one(response.text, "[data-curl]"))

    def test_a_write_waits_for_its_confirmation(self, signed_in: TestClient) -> None:
        form = {"route": NEW, "body": '{"name": "pen"}'}

        refused = signed_in.post(f"{overseer_requests.PARTIALS}/execute", data=form)
        sent = signed_in.post(
            f"{overseer_requests.PARTIALS}/execute", data=form | {"confirm": "on"}
        )

        assert triggers(refused)["toast"]["tone"] == "error"
        assert one(sent.text, "[data-status]").text.strip() == "200"


class TestLoadTests:
    def test_the_route_picker_loads_the_same_form(self, signed_in: TestClient) -> None:
        html = _form(signed_in, ITEM, mode="load")
        form = one(html, "form")
        assert form.get("hx-post") == overseer_server_load_tests.PARTIALS
        one(form, 'input[name="path.item_id"]')
        one(form, 'input[name="requests"]')

    def test_load_test_this_brings_the_values_along(
        self, signed_in: TestClient
    ) -> None:
        url = (
            "/overseer/components/backend/load-tests"
            f"?route={quote(ITEM)}&path.item_id=7&query.q=hi"
        )
        html = page_html(signed_in, url)
        assert one(html, 'input[name="path.item_id"]').get("value") == "7"
        assert one(html, 'input[name="query.q"]').get("value") == "hi"

    def test_a_run_needs_what_the_route_needs(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = FakeRunner()
        monkeypatch.setattr(
            overseer_server_load_tests, "get_job_runner", lambda: runner
        )
        form = {"route": ITEM, "requests": "10", "clients": "2"}

        refused = signed_in.post(overseer_server_load_tests.PARTIALS, data=form)
        sent = signed_in.post(
            overseer_server_load_tests.PARTIALS, data=form | {"path.item_id": "7"}
        )

        assert "item_id" in triggers(refused)["toast"]["text"]
        assert triggers(sent)["toast"]["tone"] == "ok" and len(runner.started) == 1
