"""The browser in the htmx Overseer: its own sidebar entry under Compute,
and the generic page showing where the server is and which client talks
to it."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.browser.health import BrowserFact
from app.components.web_frontend.overseer_sections import CONCERNS
from app.components.web_frontend.rendering import templates
from app.core.constants import ComponentName
from app.services.system.models import ComponentStatus, ComponentStatusType
from tests.web.dom import one, select, text
from tests.web.overseer import sign_in, status_with

BROWSER = ComponentStatus(
    name=ComponentName.BROWSER,
    status=ComponentStatusType.HEALTHY,
    message="Browser server reachable",
    metadata={BrowserFact.ENDPOINT: "ws://browser:3000/", BrowserFact.CLIENT: "1.63.0"},
)


def test_the_page_shows_the_server_and_the_client(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app, monkeypatch, status_with(BROWSER))
    with TestClient(app) as client:
        details = one(client.get("/overseer/components/browser").text, "#card-details")
    facts = dict(
        zip(
            [text(d) for d in select(details, "dt")],
            [text(d) for d in select(details, "dd")],
            strict=True,
        )
    )
    assert facts == {"Endpoint": "ws://browser:3000/", "Client": "1.63.0"}


def test_it_sits_under_compute_with_an_icon_of_its_own() -> None:
    assert ComponentName.BROWSER in dict(CONCERNS)["Compute"]
    module = templates.env.get_template("components/macros/layout.html").module
    assert str(module.sidebar_icon(ComponentName.BROWSER)) != str(
        module.sidebar_icon("unknown")
    )
