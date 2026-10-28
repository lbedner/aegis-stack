"""Where the dashboard may make an operator's change: its own address, the
one the browser opened it at (as htmx's pages are judged), since it calls
the API from inside its own process (``OWN_API``), at a loopback name. Its
client names that page as its ``Origin``, so the API refuses a change from
it where it refuses a browser's (``refusal_at``)."""

from importlib.util import find_spec

import pytest

from app.components.frontend.core.changes import (
    OWN_API,
    dashboard_client,
    page_refusal,
)
from app.core.config import settings
from app.services.shared.deps import NO_AUTH_REFUSAL, refusal_at
from tests.components.frontend._fakes import FakePage

pytestmark = pytest.mark.skipif(
    find_spec("app.services.auth") is not None, reason="with auth: admins only"
)


def _opened_at(url: str | None) -> FakePage:
    return FakePage(url=url)


def test_the_dashboard_calls_its_own_process() -> None:
    assert OWN_API == f"http://localhost:{settings.PORT}"


def test_opened_at_localhost_it_may() -> None:
    assert page_refusal(_opened_at("http://localhost:8001/dashboard")) is None


def test_opened_at_a_lan_address_it_may_not() -> None:
    page = _opened_at("http://192.168.1.20:8001/dashboard")
    assert page_refusal(page) == NO_AUTH_REFUSAL


def test_a_deployed_build_may_not_even_at_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    page = _opened_at("http://localhost:8001/dashboard")
    assert page_refusal(page) == NO_AUTH_REFUSAL


def test_with_no_page_to_ask_it_may_not() -> None:
    assert page_refusal(None) == NO_AUTH_REFUSAL


def _asked(page: FakePage) -> str | None:
    """What the API says to a change the dashboard on ``page`` sends."""
    client = dashboard_client(page)
    return refusal_at(f"{client.base_url}/api/v1/x", client.origin)


def test_its_client_names_its_page() -> None:
    page = _opened_at("http://192.168.1.20:8001/dashboard")
    assert dashboard_client(page).origin == "http://192.168.1.20:8001"


def test_the_api_refuses_a_change_from_a_page_opened_on_the_lan() -> None:
    assert _asked(_opened_at("http://192.168.1.20:8001/dashboard")) == NO_AUTH_REFUSAL


def test_the_api_takes_a_change_from_a_page_opened_at_localhost() -> None:
    assert _asked(_opened_at("http://localhost:8001/dashboard")) is None


def test_a_page_with_no_address_names_none() -> None:
    """``null``, as a browser sends for a page it will not name: refused."""
    assert _asked(_opened_at(None)) == NO_AUTH_REFUSAL
