"""The Overseer Authentication page: Overview, Users and Sessions, read-only."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_auth
from app.components.web_frontend.routes.partials import overseer_auth as partials
from app.core.db import get_async_db
from app.core.security import create_access_token
from app.models.refresh_token import SessionEnd, SessionHistory
from app.models.user import User, UserResponse
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
EARLIER = NOW - timedelta(hours=3)
# The users the sessions belong to (1 is the signed-in viewer).
PEOPLE = {
    1: User(id=1, email="ops@example.com", full_name="Ops", hashed_password="x"),
    2: User(id=2, email="dana@example.com", full_name="Dana", hashed_password="x"),
}
SESSIONS = [
    SessionHistory(
        id="fam-1",
        user_id=2,
        source="oauth:github",
        user_agent="Firefox on Linux",
        ip="10.0.0.2",
        signed_in=EARLIER,
        renewals=[NOW - timedelta(hours=2), NOW - timedelta(hours=1)],
        last_used_at=NOW,
        expires_at=NOW + timedelta(days=14),
    ),
    SessionHistory(
        id="fam-here",
        user_id=1,
        source="password",
        user_agent="Safari on macOS",
        ip="10.0.0.3",
        signed_in=EARLIER,
        renewals=[],
        last_used_at=NOW,
        expires_at=NOW + timedelta(days=14),
    ),
    SessionHistory(
        id="fam-mine",
        user_id=1,
        source="password",
        user_agent="Firefox on Windows",
        ip="10.0.0.4",
        signed_in=EARLIER,
        renewals=[],
        last_used_at=EARLIER,
        expires_at=NOW + timedelta(days=14),
    ),
    SessionHistory(
        id="fam-gone",
        user_id=1,
        source="password",
        user_agent="python-httpx/0.28.1",
        ip="127.0.0.1",
        signed_in=EARLIER,
        renewals=[],
        last_used_at=EARLIER,
        expires_at=EARLIER,
        ended=SessionEnd.EXPIRED,
        ended_at=EARLIER,
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

    async def history(db: Any, _viewer: Any) -> list[SessionHistory]:
        assert db is REQUEST_SESSION
        return SESSIONS

    async def people(db: Any, ids: list[int]) -> dict[int, User]:
        assert db is REQUEST_SESSION
        return {uid: PEOPLE[uid] for uid in ids if uid in PEOPLE}

    async def session(db: Any, family_id: str) -> SessionHistory | None:
        assert db is REQUEST_SESSION
        return next((s for s in SESSIONS if s.id == family_id), None)

    async def counts(db: Any) -> dict[int, int]:
        assert db is REQUEST_SESSION
        return {2: 1}

    async def request_session() -> Any:
        return REQUEST_SESSION

    app.dependency_overrides[get_async_db] = request_session
    monkeypatch.setattr(overseer_auth, "load_users", users)
    monkeypatch.setattr(overseer_auth, "load_history", history)
    monkeypatch.setattr(overseer_auth, "load_people", people)
    monkeypatch.setattr(overseer_auth, "load_session", session)
    monkeypatch.setattr(overseer_auth, "load_session_counts", counts)
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


def _rows(html: str) -> list[Any]:
    return select(html, "tbody tr")


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

    def test_each_user_says_how_many_sessions_and_links_to_them(
        self, signed_in: TestClient
    ) -> None:
        """Where an administrator acts on a person: their live sessions,
        one click from the devices themselves."""
        ops, gone = (row.cssselect("td")[6] for row in _rows(_get(signed_in, "users")))
        link = one(gone, "a")
        assert text(link) == "1"
        assert link.get("href").endswith("/sessions?user=2")
        none(ops, "a")
        assert text(ops) == "-"  # none live


def _live(html: str) -> list[Any]:
    """The live sessions' rows, each without its details row."""
    return select(html, "[data-sessions] tbody > tr:first-child")


def _details(html: str) -> list[Any]:
    """The live sessions' opened details, one per row."""
    return select(html, "[data-sessions] tr[data-detail]")


class TestSessions:
    def test_lists_sessions(self, signed_in: TestClient) -> None:
        row = _live(_get(signed_in, "sessions"))[0]
        assert ["Dana", "GitHub", "Firefox on Linux"] == [
            text(td) for td in row.cssselect("td")
        ][1:4]

    def test_the_card_says_how_long_each_token_lasts(
        self, signed_in: TestClient
    ) -> None:
        """The session cookie renews from the refresh token: both lifetimes
        head the card, so an hourly renewal reads as expected."""
        head = text(one(_get(signed_in, "sessions"), "[data-lifetimes]"))
        assert "Session cookie" in head and "Refresh token 14 days" in head

    def test_a_session_says_how_often_it_renewed(self, signed_in: TestClient) -> None:
        rows = _live(_get(signed_in, "sessions"))
        assert "2 times" in text(rows[0]) and "Not yet" in text(rows[1])

    def test_a_sessions_details_name_its_renewals_and_this_browsers_cookie(
        self, signed_in: TestClient
    ) -> None:
        """Opened: where and what it signed in from, each renewal, and for
        this browser, when its session cookie runs out and renews."""
        _browse_as(signed_in, "fam-here")
        html = _get(signed_in, "sessions")
        details = _details(html)
        assert "10.0.0.2" in text(details[0])
        renewed = text(details[0])
        for at in SESSIONS[0].renewals:  # clock times: a burst reads apart
            assert at.strftime("%b %d %H:%M") in renewed
        assert "renews from the refresh token" in text(details[1])

    def test_renewals_all_listed_say_no_more(self, signed_in: TestClient) -> None:
        """Every renewal fits the list: the row has the count, and a first-
        to-last range would only repeat the list."""
        detail = _details(_get(signed_in, "sessions"))[0]
        labels = [text(dt) for dt in detail.cssselect("dt")]
        assert "Renewals" in labels and "Renewed" not in labels

    def test_renewals_past_the_list_say_their_range(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """More renewals than the list shows: the range says how far back."""
        monkeypatch.setattr(overseer_auth, "RENEWALS_SHOWN", 1)
        detail = _details(_get(signed_in, "sessions"))[0]
        labels = [text(dt) for dt in detail.cssselect("dt")]
        assert "Renewed" in labels and "Latest renewals" in labels
        first, last = SESSIONS[0].renewals
        assert first.strftime("%b %d %H:%M") in text(detail)

    def test_ended_sessions_say_when_and_how(self, signed_in: TestClient) -> None:
        """The last week's ended sign-ins, so a sign-out has a reason."""
        html = _get(signed_in, "sessions")
        ended = select(html, "[data-ended] tbody tr")
        assert len(ended) == 1
        assert "python-httpx 0.28.1" in text(ended[0])
        assert "Expired" in text(ended[0])
        assert "python-httpx" not in text(one(html, "[data-sessions]"))

    def test_a_device_is_its_browser_and_system_whole_on_hover(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole user-agent string ran the table past its card: the
        device reads short, and says the rest on hover."""
        agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        )
        chrome = SESSIONS[0].model_copy(update={"user_agent": agent})

        async def history(*_: Any, **__: Any) -> list[SessionHistory]:
            return [chrome]

        monkeypatch.setattr(overseer_auth, "load_history", history)
        device = one(_get(signed_in, "sessions"), "[data-sessions] [data-device]")
        assert (text(device), device.get("title")) == ("Chrome 154 · macOS", agent)

    def test_marks_this_browser_and_offers_it_no_sign_out(
        self, signed_in: TestClient
    ) -> None:
        """Signing out this browser is the Sign out link, not a row action
        that leaves the page broken."""
        _browse_as(signed_in, "fam-here")
        html = _get(signed_in, "sessions")
        rows = _live(html)
        assert "This browser" in text(rows[1])
        assert "This browser" not in text(rows[0])
        assert [b.get("hx-get") for b in select(html, "tbody button[hx-get]")] == [
            "/partials/overseer/auth/confirm/revoke/fam-1",
            "/partials/overseer/auth/confirm/revoke/fam-mine",
        ]

    def test_an_admin_sees_everyones_sessions_and_whose(
        self, signed_in: TestClient
    ) -> None:
        """Overseer runs the app: every user's sign-ins, each with its user."""
        rows = _live(_get(signed_in, "sessions"))
        assert [text(row.cssselect("td")[1]) for row in rows] == [
            "Dana",
            "Ops",
            "Ops",
        ]

    def test_a_name_opens_that_users_sessions(self, signed_in: TestClient) -> None:
        """No list of every user to pick from (it would not scale): a name
        in the table narrows to that user, and one link widens it again."""
        html = _get(signed_in, "sessions")
        link = one(_live(html)[0].cssselect("td")[1], "a")
        assert link.get("href").endswith("/sessions?user=2")
        narrowed = _get(signed_in, "sessions?user=2")
        assert len(_live(narrowed)) == 1
        showing = one(narrowed, "[data-showing]")
        assert "Dana" in text(showing)
        assert one(showing, "a").get("href").endswith("/sessions")

    @pytest.mark.parametrize(("q", "count"), [("dana", 1), ("OPS@EXAMPLE", 2)])
    def test_a_search_finds_sessions_by_their_users_name_or_email(
        self, signed_in: TestClient, q: str, count: int
    ) -> None:
        html = _get(signed_in, f"sessions?q={q}")
        assert len(_live(html)) == count
        assert one(html, "input[name=q]").get("value") == q

    def test_the_sessions_come_a_page_at_a_time(
        self, signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(overseer_auth, "PAGE_SIZE", 2)
        html = _get(signed_in, "sessions")
        assert len(_live(html)) == 2
        later = one(html, 'nav[aria-label="Pagination"] a[rel="next"]')
        assert "page=2" in later.get("href")
        assert len(_live(_get(signed_in, "sessions?page=2"))) == 1


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
        # Signing someone out everywhere lives with the rest of what is done
        # to a person; only a user with live sessions, never the viewer
        # (theirs is "everywhere else", on Sessions).
        assert openers == [
            "/partials/overseer/auth/confirm/deactivate/1",
            "/partials/overseer/auth/confirm/delete/1",
            "/partials/overseer/auth/confirm/activate/2",
            "/partials/overseer/auth/confirm/revoke-user/2",
            "/partials/overseer/auth/confirm/delete/2",
        ]

    @pytest.mark.parametrize(
        ("path", "verb", "url"),
        [
            ("deactivate/1", "hx-patch", "/api/v1/auth/users/1/deactivate"),
            ("activate/2", "hx-patch", "/api/v1/auth/users/2/activate"),
            ("delete/1", "hx-delete", "/api/v1/auth/users/1"),
            ("revoke/fam-mine", "hx-delete", "/api/v1/auth/sessions/fam-mine"),
            # Someone else's: the admin route, scoped to its user.
            ("revoke/fam-1", "hx-delete", "/api/v1/auth/users/2/sessions/fam-1"),
            ("revoke-user/2", "hx-delete", "/api/v1/auth/users/2/sessions"),
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

    @pytest.mark.parametrize(
        "path",
        [
            "nope/1",
            "delete/99",
            "revoke/other-family",
            "revoke/fam-gone",
            # This browser's own: the Sign out link, not a dialog.
            "revoke/fam-here",
        ],
    )
    def test_unknown_action_or_target_is_404(
        self, signed_in: TestClient, path: str
    ) -> None:
        _browse_as(signed_in, "fam-here")
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
