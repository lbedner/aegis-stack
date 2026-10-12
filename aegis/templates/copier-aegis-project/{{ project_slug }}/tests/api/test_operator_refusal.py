"""An operator's change (restart a container, set a secret, end a
connection) goes through ``get_admin_actor``, or its page-side twin
``overseer_actor``, and every other Overseer write through Overseer's gate.
With auth that is admins only. Without it, only the undeployed dev build,
asked at a loopback address (``operator_refusal``): anyone else is refused,
with the line the UI shows where it hides the controls.

The walk below covers every route behind either dependency and every
Overseer route that is not a read, so a write added later is refused
without remembering to be."""

from collections.abc import Callable, Iterator
from importlib.util import find_spec
from pathlib import Path
import re
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.services.shared.deps import (
    NO_AUTH_REFUSAL,
    get_admin_actor,
    refusal_at,
)

NO_AUTH = find_spec("app.services.auth") is None
without_auth = pytest.mark.skipif(not NO_AUTH, reason="with auth: admins only")


def _operator_deps() -> set[Callable[..., Any]]:
    """The dependencies that make a change an operator's."""
    found: set[Callable[..., Any]] = {get_admin_actor}
    if find_spec("app.components.web_frontend") is not None:
        from app.components.web_frontend.overseer_access import overseer_actor

        found.add(overseer_actor)
    return found


def _calls(dependant: Dependant) -> Iterator[Any]:
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


OVERSEER = ("/overseer", "/partials/overseer")
READS = {"GET", "HEAD", "OPTIONS"}


def _writes(route: APIRoute, wanted: set[Callable[..., Any]]) -> set[str]:
    """``route``'s methods that make a change: all of them behind an
    operator dependency, any but a read under Overseer."""
    if wanted & set(_calls(route.dependant)):
        return set(route.methods)
    if not route.path.startswith(OVERSEER) or route.path in _public():
        return set()
    return set(route.methods) - READS


def _public() -> frozenset[str]:
    """Overseer's way in (with auth, its sign-in form), open to anyone."""
    from app.components.web_frontend import overseer_access

    return getattr(overseer_access, "PUBLIC", frozenset())


def operator_calls(app: FastAPI) -> list[tuple[str, str]]:
    """Every (method, path) that makes an operator's change, path
    parameters filled in."""
    wanted = _operator_deps()
    found = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not (methods := _writes(route, wanted)):
            continue
        path = route.path
        for name in route.param_convertors:
            path = path.replace("{" + name + ":path}", "x").replace(
                "{" + name + "}", "1"
            )
        found.extend((method, path) for method in sorted(methods))
    return found


def test_the_walk_finds_the_write_actions(app: FastAPI) -> None:
    calls = operator_calls(app)
    if find_spec("app.components.deploy") is not None:
        assert ("POST", "/api/v1/runtime/containers/1/restart") in calls
    if find_spec("app.components.web_frontend") is not None:
        assert any(path.startswith(OVERSEER) for _, path in calls)


def test_anonymous_on_another_host_is_refused_every_action(app: FastAPI) -> None:
    """``testserver`` is not a loopback address: refused, each one (with
    auth, signed out: 401 or 403 before the change is looked at)."""
    client = TestClient(app, raise_server_exceptions=False)
    let_through = [
        (method, path, response.status_code)
        for method, path in operator_calls(app)
        if (
            response := client.request(method, path, follow_redirects=False)
        ).status_code
        not in ((403,) if NO_AUTH else (401, 403))
    ]
    assert not let_through, f"an operator's change let through: {let_through}"


@without_auth
def test_the_refusal_says_why(app: FastAPI) -> None:
    calls = operator_calls(app)
    if not calls:
        pytest.skip("this stack has no operator's change to refuse")
    method, path = calls[0]
    response = TestClient(app).request(method, path)
    assert response.status_code == 403
    assert response.json()["detail"] == NO_AUTH_REFUSAL


@without_auth
@pytest.mark.parametrize(
    "url",
    ["http://localhost:8000/x", "http://127.0.0.1:8000/x", "http://[::1]:8000/x"],
)
def test_the_local_dev_build_at_a_loopback_address_may(url: str) -> None:
    assert refusal_at(url) is None


@without_auth
@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.20:8000/x",  # the laptop's address, from the LAN
        "http://app.example.com/x",  # a name, which may resolve anywhere
        "http://localhost.example.com/x",
        "http://testserver/x",
    ],
)
def test_any_other_address_is_refused(url: str) -> None:
    assert refusal_at(url) == NO_AUTH_REFUSAL


@without_auth
def test_a_deployed_build_is_refused_even_at_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``aegis deploy`` stamps BUILD_ID; an SSH tunnel to the server's
    localhost is still the server."""
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    assert refusal_at("http://localhost:8000/x") == NO_AUTH_REFUSAL


@without_auth
@pytest.mark.parametrize("origin", ["https://evil.example", "null"])
def test_another_sites_page_is_refused_even_at_localhost(origin: str) -> None:
    """A page elsewhere posting to localhost from the developer's own
    browser: its ``Origin`` is not loopback."""
    assert refusal_at("http://localhost:8000/x", origin) == NO_AUTH_REFUSAL


@without_auth
def test_the_apps_own_page_at_localhost_may() -> None:
    assert refusal_at("http://localhost:8000/x", "http://localhost:8000") is None


def test_with_auth_nothing_is_refused_here() -> None:
    """With auth the admin check is ``require_admin``'s, wherever they are."""
    if NO_AUTH:
        pytest.skip("without auth: the rule above")
    assert refusal_at("http://app.example.com/x") is None


PAGES = Path("app/components/web_frontend/templates/pages/overseer")
WRITES = re.compile(r'hx-(?:post|put|delete|patch)=|hx_dialog_post\(|method="post"')
FORMS = re.compile(r"<form\b.*?</form>", re.S)


def unmarked_writes(source: str) -> list[str]:
    """The write controls in a template's ``source`` that do not carry
    ``data-write``: a form counts once (on the form, or on its submit, so
    an editor stays readable), anything else line by line."""
    found = [
        form.split("\n", 1)[0]
        for form in FORMS.findall(source)
        if WRITES.search(form) and "data-write" not in form
    ]
    rest = FORMS.sub("", source)
    found += [
        line
        for line in rest.splitlines()
        if WRITES.search(line) and "data-write" not in line
    ]
    return found


@pytest.mark.skipif(not PAGES.is_dir(), reason="no htmx Overseer in this stack")
def test_every_overseer_write_control_hides_where_writes_are_refused() -> None:
    """The shell hides ``data-write`` where ``operator_refusal`` refuses."""
    unmarked = {
        str(path.relative_to(PAGES)): found
        for path in sorted(PAGES.rglob("*.html"))
        if path.name != "login.html"  # the way in
        and (found := unmarked_writes(path.read_text()))
    }
    assert not unmarked, f"write controls without data-write: {unmarked}"


def test_the_scan_sees_an_unmarked_control() -> None:
    assert unmarked_writes('<button hx-post="/x">Go</button>')
    assert unmarked_writes('<form hx-post="/x"><button>Go</button></form>')
    assert not unmarked_writes(
        '<form hx-post="/x"><button data-write>Go</button></form>'
    )
