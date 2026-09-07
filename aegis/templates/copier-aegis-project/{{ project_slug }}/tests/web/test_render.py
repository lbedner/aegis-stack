"""``render()``: one route, two render paths.

A page template ends with ``{% extends layout %}``; the helper sets
``layout`` to the page layout for a full load and to the bare fragment when
htmx asks, so no view ever needs two URLs or two templates.
"""

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest
from starlette.responses import Response

from app.components.web_frontend.rendering import render
from tests.web.dom import none, one, text

PROBE_PAGE = (
    "{% extends layout %}"
    '{% block app_content %}<p id="probe">{{ word }}</p>{% endblock %}'
)


@pytest.fixture
def app(add_template: Callable[[str, str], None]) -> FastAPI:
    add_template("pages/_probe.html", PROBE_PAGE)
    tiny = FastAPI()

    @tiny.get("/probe")
    def probe(request: Request) -> Response:
        return render(request, "pages/_probe.html", {"word": "hi"})

    @tiny.get("/probe-422")
    def probe_422(request: Request) -> Response:
        return render(request, "pages/_probe.html", {"word": "bad"}, status_code=422)

    return tiny


class TestRender:
    def test_full_load_renders_inside_the_page_layout(
        self, client: TestClient
    ) -> None:
        page = client.get("/probe").text
        one(page, "head title")
        one(page, "main#app-content #probe")

    def test_htmx_request_renders_the_bare_fragment(self, hx: TestClient) -> None:
        fragment = hx.get("/probe").text
        one(fragment, "#probe")
        none(fragment, "html")
        none(fragment, "main")

    def test_boosted_request_is_a_full_load(self, client: TestClient) -> None:
        """``hx-boost`` swaps the whole body, so it needs the full page."""
        page = client.get(
            "/probe", headers={"HX-Request": "true", "HX-Boosted": "true"}
        ).text
        one(page, "head title")

    def test_context_reaches_the_template(self, hx: TestClient) -> None:
        assert text(one(hx.get("/probe").text, "#probe")) == "hi"

    def test_status_code_passes_through(self, hx: TestClient) -> None:
        """Validation re-renders (pattern 1) return the form with a 422."""
        response = hx.get("/probe-422")
        assert response.status_code == 422
        one(response.text, "#probe")

    def test_response_varies_on_the_htmx_header(self, client: TestClient) -> None:
        """Same URL, two bodies: caches must key on the header or a full
        load could be served a fragment."""
        assert "HX-Request" in client.get("/probe").headers["vary"]
