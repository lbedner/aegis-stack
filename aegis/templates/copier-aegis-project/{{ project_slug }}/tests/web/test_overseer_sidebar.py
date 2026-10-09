"""The Overseer sidebar, grouped by kind (components, services) or by
concern (stack, compute, data, AI, app, platform): the viewer's choice."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_sections
from app.core.constants import ComponentName, ServiceName
from app.services.system.models import ComponentStatus
from tests.web.dom import one, select, text
from tests.web.overseer import page_html, reported_only, sign_in, status_with


def _entry(name: str) -> ComponentStatus:
    return ComponentStatus(name=name, message="ok")


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    reported_only(monkeypatch)
    status = status_with(
        _entry(ComponentName.BACKEND),
        _entry(ComponentName.CACHE),
        services=[
            _entry(ServiceName.AUTH),
            _entry(ServiceName.DOCUMENTS),
            _entry("crm"),
        ],
    )
    sign_in(app, monkeypatch, status)
    return TestClient(app)


def _grouping(html: str) -> set[str | None]:
    """The grouping each menu (the sidebar's, the phone's) shows chosen."""
    chosen = select(html, '[data-set-grouping][aria-pressed="true"]')
    return {b.get("data-set-grouping") for b in chosen}


def _sections(html: str) -> dict[str, list[str]]:
    return {
        text(one(s, "h2")): [a.get("title") for a in select(s, "a")]
        for s in select(html, "#overseer-nav section")
    }


def _hrefs(html: str) -> list[str]:
    return sorted(a.get("href") for a in select(html, "#overseer-nav a"))


def test_by_kind_until_the_viewer_picks_concern(client: TestClient) -> None:
    html = page_html(client, "/overseer")
    assert list(_sections(html)) == ["Components", "Services"]
    assert _grouping(html) == {overseer_sections.Grouping.KIND}


def test_by_concern_every_page_in_its_section_at_its_own_address(
    client: TestClient,
) -> None:
    """A regrouping, not new pages: the same links, each once, under the
    concern it serves (a service among the components it sits with); one
    no concern names (a plugin's) joins the app's."""
    kind = page_html(client, "/overseer")
    client.cookies.set(
        overseer_sections.GROUPING_COOKIE, overseer_sections.Grouping.CONCERN
    )
    html = page_html(client, "/overseer")
    sections = _sections(html)
    assert list(sections) == ["Stack", "Compute", "Data", "App", "Platform"]
    assert sections["Stack"][0] == "Overview"
    assert sections["Data"] == ["Cache", "Documents"]
    assert sections[overseer_sections.APP][-1] == "crm".title()
    assert _hrefs(html) == _hrefs(kind)
    assert _grouping(html) == {overseer_sections.Grouping.CONCERN}


def test_collapse_sits_in_the_head_and_the_rest_in_one_menu(
    client: TestClient,
) -> None:
    """The footer is one row: the viewer's menu, with the appearance, the
    grouping and, for a signed-in viewer (named on it), Sign out. A phone
    has the same menu in the page's header. Collapsing is in the head."""
    html = page_html(client, "/overseer")
    one(html, '[data-sidebar-head] button[aria-controls="overseer-sidebar"]')
    assert len(select(html, "[data-sidebar-foot] > *")) == 1
    menus = [d for d in select(html, "details") if select(d, "[data-set-grouping]")]
    assert len(menus) == 2
    for menu in menus:
        for setting in ("theme", "mode", "grouping"):
            assert select(menu, f"[data-set-{setting}]")
        signed_in = text(one(menu, "summary")) != "Appearance"
        assert bool(select(menu, 'a[href="/logout"]')) == signed_in
