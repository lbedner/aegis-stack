"""A service brings its own Overseer page: ``OVERSEER`` in its ``overseer``
module names the page's module and partials, and Overseer lists it under
the service with no edit to the framework's own files."""

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter
import pytest

from app.components.web_frontend import overseer_sections
from app.components.web_frontend.overseer_nav import build_navigation
from app.components.web_frontend.overseer_sections import _optional_pages
from app.core.overseer_pages import include_partials

_PAGE = (
    "SECTIONS = ((None, {'overview': 'Overview', 'notes': 'Notes'}),)\n"
    "async def section_context(section, component, req):\n"
    "    return {'section': section}\n"
)
_PARTIALS = (
    "from fastapi import APIRouter\n"
    "router = APIRouter()\n"
    "@router.post('/partials/overseer/{name}/note')\n"
    "async def note() -> None: ...\n"
)
_OVERSEER = (
    "from app.core.overseer_pages import OverseerPage\n"
    "OVERSEER = OverseerPage(\n"
    "    'app.services.{name}.page', 'app.services.{name}.partials',\n"
    "    when=lambda: {shown},\n"
    ")\n"
)


def _with_page(
    fake_service: Callable[..., Path], name: str, shown: bool = True
) -> None:
    fake_service(
        name,
        page=_PAGE,
        partials=_PARTIALS.replace("{name}", name),
        overseer=_OVERSEER.format(name=name, shown=shown),
    )


def _partials_mounted() -> set[str]:
    router = APIRouter()
    include_partials(router)
    return {route.path for route in router.routes}  # type: ignore[attr-defined]


def test_a_services_page_is_listed_under_it(
    fake_service: Callable[..., Path],
) -> None:
    _with_page(fake_service, "demo_page")

    page = _optional_pages()[("services", "demo_page")]

    assert page.folder == "demo_page"
    assert page.labels == {"overview": "Overview", "notes": "Notes"}
    assert "/partials/overseer/demo_page/note" in _partials_mounted()


def test_a_page_with_no_health_check_is_still_on_the_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(overseer_sections, "SERVICE_PAGES", frozenset({"demo_railed"}))

    rail = {item.name: item for item in build_navigation(None)["services"]}

    assert rail["demo_railed"].component.message == "No health check"
    assert rail["demo_railed"].url == "/overseer/services/demo_railed"


def test_a_page_its_service_holds_back_is_not_listed(
    fake_service: Callable[..., Path],
) -> None:
    _with_page(fake_service, "demo_hidden", shown=False)

    assert ("services", "demo_hidden") not in _optional_pages()
    assert "/partials/overseer/demo_hidden/note" not in _partials_mounted()
