"""The Overseer Authentication page: Overview, Users and Sessions, read-only."""

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_auth
from app.components.web_frontend.routes.partials import overseer_auth as partials
from app.core.db import get_async_db
from app.core.security import create_access_token
from app.models.refresh_token import SessionResponse
from app.models.user import UserResponse
from app.services.system.models import ComponentStatus
from tests.web.dom import none, one, select, text
from tests.web.overseer import sign_in, status_with

METADATA: dict[str, Any] = {
    "database_available": True,
    "user_count_display": "2",
    "jwt_algorithm": "HS256",
    "token_expiry_display": "30 minutes",
    "secret_key_configured": True,
    "secret_key_length": 64,
    "security_level": "standard",
    "configuration_issues": ["Consider RS256"],
}

NOW = datetime.now(UTC)
# SQLite takes its write lock at BEGIN, so a second session opened while the
# request's own session is live waits it out and fails "database is locked".
# The loaders must use the request's session; this stands in for it.
REQUEST_SESSION = object()
USERS = [
    UserResponse(
        id=1,
        email="ops@example.com",
        full_name="Ops",
        is_active=True,
        is_verified=True,
        created_at=NOW,
    ),
    UserResponse(
        id=2,
        email="gone@example.com",
        is_active=False,
        is_verified=False,
        created_at=NOW,
    ),
]
SESSIONS = [
    SessionResponse(
        id="fam-1",
        source="oauth:github",
        user_agent="Firefox on Linux",
        ip="10.0.0.2",
        created_at=NOW,
        last_used_at=NOW,
        expires_at=NOW,
        is_current=False,
    ),
    SessionResponse(
        id="fam-here",
        source="password",
        user_agent="Safari on macOS",
        ip="10.0.0.3",
        created_at=NOW,
        last_used_at=NOW,
        expires_at=NOW,
        is_current=False,
    ),
]


def _browse_as(client: TestClient, session_id: str) -> None:
    """This browser's session cookie, an access token for ``session_id``."""
    client.cookies.set(
        "aegis_session",
        create_access_token({"sub": "ops@example.com", "sid": session_id}),
    )


def _client(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, Any]
) -> TestClient:
    auth = ComponentStatus(name="auth", message="Auth ready", metadata=metadata)
    sign_in(app, monkeypatch, status_with(services=[auth]))

    async def users(db: Any) -> list[UserResponse]:
        assert db is REQUEST_SESSION
        return USERS

    async def sessions(
        db: Any, _viewer: Any, current: str | None = None
    ) -> list[SessionResponse]:
        assert db is REQUEST_SESSION
        return [s.model_copy(update={"is_current": s.id == current}) for s in SESSIONS]

    async def request_session() -> Any:
        return REQUEST_SESSION

    app.dependency_overrides[get_async_db] = request_session
    monkeypatch.setattr(overseer_auth, "load_users", users)
    monkeypatch.setattr(overseer_auth, "load_sessions", sessions)
    return TestClient(app)


@pytest.fixture
def signed_in(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    with _client(app, monkeypatch, METADATA) as client:
        yield client


def _get(client: TestClient, section: str = "") -> str:
    response = client.get(
        "/overseer/services/auth" + (f"/{section}" if section else "")
    )
    assert response.status_code == 200
    return response.text


def _cells(html: str) -> list[list[str]]:
    return [
        [text(td) for td in row.cssselect("td")] for row in select(html, "tbody tr")
    ]


class TestSections:
    def test_overview_then_manage(self, signed_in: TestClient) -> None:
        subnav = one(_get(signed_in), "#overseer-subnav")
        assert text(one(subnav, "h2")) == "Authentication"
        assert [text(h) for h in select(subnav, "h3")] == ["Manage"]
        assert [text(a) for a in select(subnav, "nav a")] == [
            "Overview",
            "Users",
            "Sessions",
            "Settings",
        ]


class TestOverview:
    def test_figures_configuration_and_security(self, signed_in: TestClient) -> None:
        html = _get(signed_in)
        figures = {
            text(one(c, "dt")): text(one(c, "dd"))
            for c in select(html, "#auth-figures > div")
        }
        assert figures == {
            "Total users": "2",
            "JWT algorithm": "HS256",
            "Token expiry": "30 minutes",
        }
        assert "Strong (64 chars)" in text(one(html, "#card-configuration"))
        security = text(one(html, "#card-security"))
        assert "Standard" in security
        assert "Consider RS256" in security


class TestUsers:
    def test_lists_users_with_state(self, signed_in: TestClient) -> None:
        rows = _cells(_get(signed_in, "users"))
        assert rows[0][:4] == ["ops@example.com", "Ops", "Active", "Verified"]
        assert rows[1][:4] == ["gone@example.com", "-", "Disabled", "Unverified"]


class TestSessions:
    def test_lists_sessions(self, signed_in: TestClient) -> None:
        rows = _cells(_get(signed_in, "sessions"))
        assert rows[0][:3] == ["GitHub", "Firefox on Linux", "10.0.0.2"]

    def test_marks_this_browser_and_offers_it_no_sign_out(
        self, signed_in: TestClient
    ) -> None:
        """Signing out this browser is the Sign out link, not a row action
        that leaves the page broken."""
        _browse_as(signed_in, "fam-here")
        html = _get(signed_in, "sessions")
        rows = select(html, "tbody tr")
        assert "This browser" in text(rows[1])
        assert "This browser" not in text(rows[0])
        assert [b.get("hx-get") for b in select(html, "tbody button[hx-get]")] == [
            "/partials/overseer/auth/confirm/revoke/fam-1"
        ]


class TestActions:
    """Each action opens a confirmation, whose button calls the auth API
    itself, as Flet does, so the API keeps its permissions and audit."""

    def _confirm(self, client: TestClient, path: str) -> Any:
        response = client.get(f"/partials/overseer/auth/confirm/{path}")
        assert response.status_code == 200
        return one(response.text, "button[data-api-done]")

    def test_user_rows_offer_disable_or_enable_and_delete(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in, "users")
        openers = [b.get("hx-get") for b in select(html, "tbody button[hx-get]")]
        assert openers == [
            "/partials/overseer/auth/confirm/deactivate/1",
            "/partials/overseer/auth/confirm/delete/1",
            "/partials/overseer/auth/confirm/activate/2",
            "/partials/overseer/auth/confirm/delete/2",
        ]

    @pytest.mark.parametrize(
        ("path", "verb", "url"),
        [
            ("deactivate/1", "hx-patch", "/api/v1/auth/users/1/deactivate"),
            ("activate/2", "hx-patch", "/api/v1/auth/users/2/activate"),
            ("delete/1", "hx-delete", "/api/v1/auth/users/1"),
            ("revoke/fam-1", "hx-delete", "/api/v1/auth/sessions/fam-1"),
            ("revoke-others/all", "hx-delete", "/api/v1/auth/sessions"),
        ],
    )
    def test_confirmation_calls_the_api(
        self, signed_in: TestClient, path: str, verb: str, url: str
    ) -> None:
        button = self._confirm(signed_in, path)
        assert button.get(verb) == url
        assert button.get("data-api-done")

    def test_confirmation_names_its_target(self, signed_in: TestClient) -> None:
        response = signed_in.get("/partials/overseer/auth/confirm/delete/1")
        assert "ops@example.com" in text(one(response.text, "p"))

    def test_session_sign_out_names_the_device(self, signed_in: TestClient) -> None:
        response = signed_in.get("/partials/overseer/auth/confirm/revoke/fam-1")
        assert "Firefox on Linux" in text(one(response.text, "p"))

    @pytest.mark.parametrize("path", ["nope/1", "delete/99", "revoke/other-family"])
    def test_unknown_action_or_target_is_404(
        self, signed_in: TestClient, path: str
    ) -> None:
        assert (
            signed_in.get(f"/partials/overseer/auth/confirm/{path}").status_code == 404
        )

    def test_sessions_offer_sign_out_everywhere_else(
        self, signed_in: TestClient
    ) -> None:
        html = _get(signed_in, "sessions")
        others = one(html, 'button[hx-get$="/revoke-others/all"]')
        assert others.get("disabled") is None  # two sessions

    def test_confirmations_need_a_signed_in_user(self, client: TestClient) -> None:
        """A fragment answers 401 rather than redirecting: a redirect would
        swap the login page into the dialog."""
        response = client.get(
            "/partials/overseer/auth/confirm/delete/1", follow_redirects=False
        )
        assert response.status_code == 401


class TestWithoutDatabase:
    @pytest.mark.parametrize("section", ["users", "sessions"])
    def test_explains_why_it_is_empty(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch, section: str
    ) -> None:
        with _client(
            app, monkeypatch, METADATA | {"database_available": False}
        ) as client:
            empty = one(_get(client, section), "[data-empty]")
        assert "Database backend required" in text(empty)


class TestAddUser:
    FORM = {
        "email": "new.person@example.com",
        "full_name": "New Person",
        "password": "a-long-password",
    }

    def test_users_page_offers_it(self, signed_in: TestClient) -> None:
        button = one(
            _get(signed_in, "users"),
            'button[hx-get="/partials/overseer/auth/users/new"]',
        )
        assert text(button) == "Add user"

    def test_form_posts_to_the_partial(self, signed_in: TestClient) -> None:
        html = signed_in.get("/partials/overseer/auth/users/new").text
        form = one(html, "form")
        assert form.get("hx-post") == "/partials/overseer/auth/users"
        assert {i.get("name") for i in select(form, "input")} >= {
            "email",
            "full_name",
            "password",
        }

    def test_creates_through_the_api_handler(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        async def create_user(**kwargs: Any) -> UserResponse:
            seen.update(kwargs)
            return USERS[0]

        monkeypatch.setattr(partials, "api_create_user", create_user)
        response = signed_in.post("/partials/overseer/auth/users", data=self.FORM)
        assert response.status_code == 200
        assert seen["user_data"].email == self.FORM["email"]
        assert seen["current_user"].email == "ops@example.com"
        assert "/overseer/services/auth/users" in response.headers["HX-Location"]
        assert "User created" in response.headers["HX-Trigger"]

    def test_invalid_input_re_renders_the_form(self, signed_in: TestClient) -> None:
        response = signed_in.post(
            "/partials/overseer/auth/users", data=self.FORM | {"password": "short"}
        )
        assert response.status_code == 422
        one(response.text, 'form [role="alert"]')

    def test_api_refusal_re_renders_the_form(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def refuse(**_: Any) -> UserResponse:
            raise HTTPException(status_code=400, detail="Email already registered")

        monkeypatch.setattr(partials, "api_create_user", refuse)
        response = signed_in.post("/partials/overseer/auth/users", data=self.FORM)
        assert response.status_code == 422
        assert "Email already registered" in text(one(response.text, '[role="alert"]'))


class TestPermissions:
    """Overseer asks the same policy as the API (``may_read_users``,
    ``may_admin_users``): it calls handlers directly, so their guards
    would otherwise never run."""

    def test_a_viewer_who_may_not_read_sees_no_users(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(overseer_auth, "may_read_users", lambda _user: False)
        html = _get(signed_in, "users")
        none(html, "tbody tr")
        one(html, "[data-empty]")

    def test_a_viewer_who_may_not_administer_gets_no_actions(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(overseer_auth, "may_admin_users", lambda _user: False)
        monkeypatch.setattr(partials, "may_admin_users", lambda _user: False)
        html = _get(signed_in, "users")
        none(html, "tbody button")
        none(html, 'button[hx-get$="/users/new"]')
        assert signed_in.get("/partials/overseer/auth/users/new").status_code == 403
        assert (
            signed_in.post(
                "/partials/overseer/auth/users", data=TestAddUser.FORM
            ).status_code
            == 403
        )
        assert (
            signed_in.get("/partials/overseer/auth/confirm/delete/1").status_code == 403
        )
