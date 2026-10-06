"""The Overseer is operator access: every page, stream and action needs an
admin, not merely a signed-in user. With registration open by default, a
sign-in check alone handed the deployment (its routes, source, live Redis
values, user administration) to anyone who made an account.

Admin means the ``ADMIN_USER_EMAILS`` allowlist, or the admin role where
RBAC is installed; ``AUTH_ENABLED=False`` (dev) passes. The walk below
covers every route the app registers under the Overseer, so a page or
partial added later is gated without remembering to be.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend.overseer_access import PUBLIC
from app.core.config import settings
from app.models.user import User
from app.services.auth.deps import get_optional_user, is_admin
from tests.web.overseer import overseer_calls, sign_in, status_with


def _overseer_calls(app: FastAPI) -> list[tuple[str, str]]:
    """Every gated (method, path): all but the way in."""
    return [(m, p) for m, p in overseer_calls(app) if p not in PUBLIC]


@pytest.fixture
def member(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    sign_in(app, monkeypatch, status_with(), admin=False)
    return TestClient(app)


def test_the_walk_finds_the_overseer(app: FastAPI) -> None:
    paths = {path for _, path in _overseer_calls(app)}
    assert "/overseer" in paths
    assert any(p.startswith("/partials/overseer") for p in paths)


def test_a_member_is_refused_everywhere(app: FastAPI, member: TestClient) -> None:
    allowed = [
        (method, path, response.status_code)
        for method, path in _overseer_calls(app)
        if (
            response := member.request(method, path, follow_redirects=False)
        ).status_code
        != 403
    ]
    assert not allowed, f"reachable by a non-admin: {allowed}"


def test_the_refusal_page_says_how_to_get_in(member: TestClient) -> None:
    response = member.get("/overseer")
    assert response.status_code == 403
    assert "ADMIN_USER_EMAILS" in response.text


def test_an_admin_gets_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app, monkeypatch, status_with())
    assert TestClient(app).get("/overseer").status_code == 200


def test_signed_out_pages_go_to_login_and_the_rest_is_401(app: FastAPI) -> None:
    app.dependency_overrides[get_optional_user] = lambda: None
    client = TestClient(app)
    page = client.get("/overseer", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/overseer/login")
    assert client.get("/overseer/events").status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/overseer/components/backend", "/partials/overseer/runtime/restart/app-redis-1"],
)
def test_an_htmx_request_signed_out_takes_the_whole_page_to_login(
    app: FastAPI, path: str
) -> None:
    """A session that ran out mid-page: htmx would follow a redirect itself
    and swap the login page's (missing) main area into the shell, leaving
    it blank. A plain 401 instead, which auth.js answers by renewing the
    session from its refresh cookie, or, past that, signing in whole."""
    app.dependency_overrides[get_optional_user] = lambda: None
    response = TestClient(app).get(
        path, headers={"HX-Request": "true"}, follow_redirects=False
    )
    assert response.status_code == 401
    assert "hx-redirect" not in response.headers


def test_dev_mode_opens_the_overseer_without_signing_in(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``AUTH_ENABLED=false`` stands a dev user in for a request with no
    session at all, so the Overseer opens with nothing overridden."""
    sign_in(app, monkeypatch, status_with())
    app.dependency_overrides.pop(get_optional_user)
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    assert TestClient(app).get("/overseer", follow_redirects=False).status_code == 200


def test_login_stays_open(app: FastAPI) -> None:
    app.dependency_overrides[get_optional_user] = lambda: None
    assert TestClient(app).get("/overseer/login").status_code == 200


class TestWhoIsAdmin:
    def _user(self, **fields: object) -> User:
        return User(id=2, email="ops@example.com", hashed_password="x", **fields)

    def test_the_allowlist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "AUTH_ENABLED", True)
        monkeypatch.setattr(settings, "ADMIN_USER_EMAILS", ["ops@example.com"])
        assert is_admin(self._user())
        monkeypatch.setattr(settings, "ADMIN_USER_EMAILS", [])
        if "role" not in User.model_fields:
            assert not is_admin(self._user())

    def test_dev_mode_without_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "AUTH_ENABLED", False)
        monkeypatch.setattr(settings, "ADMIN_USER_EMAILS", [])
        assert is_admin(self._user())

    def test_the_rbac_admin_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        if "role" not in User.model_fields:
            pytest.skip("no roles without RBAC")
        monkeypatch.setattr(settings, "AUTH_ENABLED", True)
        monkeypatch.setattr(settings, "ADMIN_USER_EMAILS", [])
        assert is_admin(self._user(role="admin"))
        assert not is_admin(self._user(role="user"))


def test_a_dialog_is_refused_not_sent_to_the_login(app: FastAPI) -> None:
    """The Restart confirm is a fragment for a dialog: signed out it is 401,
    never the login page swapped into the dialog."""
    from app.components.web_frontend import overseer_container

    url = overseer_container.RESTART.format(name="app-redis-1")
    response = TestClient(app).get(url, follow_redirects=False)
    assert response.status_code == 401
