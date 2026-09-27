"""The generic Overseer page: any installed entry without a page of its own."""

from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.services.system.models import ComponentStatus
from tests.web.dom import none, one, select, text
from tests.web.overseer import sign_in, status_with

WEB = ComponentStatus(
    name="web_frontend",
    message="htmx web frontend component available",
    metadata={
        "type": "component_check",
        "framework": "Jinja2 + htmx",
        "routes": 42,
        "assets_built": False,
        "nested": {"not": "shown"},
    },
)


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    sign_in(app, monkeypatch, status_with(WEB))
    with TestClient(app) as client:
        yield client


def test_shows_what_the_health_check_publishes(signed_in: TestClient) -> None:
    html = signed_in.get("/overseer/components/web_frontend").text
    details = one(html, "#card-details")
    facts = dict(
        zip(
            [text(d) for d in select(details, "dt")],
            [text(d) for d in select(details, "dd")],
            strict=True,
        )
    )
    assert facts == {"Framework": "Jinja2 + htmx", "Routes": "42", "Assets built": "No"}


def test_an_entry_without_details_has_no_details_card(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = ComponentStatus(name="web_frontend", message="ok")
    sign_in(app, monkeypatch, status_with(bare))
    with TestClient(app) as client:
        none(client.get("/overseer/components/web_frontend").text, "#card-details")


@pytest.mark.parametrize(
    ("state", "tone"),
    [("healthy", "ok"), ("info", "muted"), ("warning", "warn"), ("unhealthy", "error")],
)
def test_status_dot_carries_its_tone(state: str, tone: str) -> None:
    """The main sidebar shows only warn/error dots; it keys on this."""
    from app.components.web_frontend.rendering import templates

    html = templates.env.get_template("pages/overseer/_status_dot.html").render(health_status=state)
    assert one(html, "[data-tone]").get("data-tone") == tone
