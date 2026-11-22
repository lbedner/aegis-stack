"""Guest sign-in (``auth[guest]``): one shared guest account, a session per
visitor. Two visitors are two sessions on one user, each ends alone, and
neither sees or ends the other's."""

from datetime import datetime

from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.backend.security import turnstile
from app.core.config import settings
from app.core.security import SESSION_COOKIE
from app.core.visitor import GUEST, GUEST_EMAIL, guest_visitor
from app.models.refresh_token import RefreshToken
from app.models.user import UserCreate
from app.services.auth.domains.sessions.guest import guest_user, visitor
from app.services.auth.domains.users.accounts import UserService

GUEST_SIGN_IN = "/api/v1/auth/guest"
SESSIONS = "/api/v1/auth/sessions"


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)


def _as_new_visitor(client: TestClient) -> str:
    """A new browser clicks "Continue as guest": its session id."""
    client.cookies.clear()
    response = client.post(GUEST_SIGN_IN)
    assert response.status_code == status.HTTP_200_OK, response.text
    (mine,) = client.get(SESSIONS).json()
    return mine["id"]


@pytest.mark.queryspy(allow_n_plus_one=True)  # each visitor lists its own
async def test_two_visitors_are_two_sessions_on_one_user(
    async_client_with_db: TestClient, async_db_session: AsyncSession
) -> None:
    first = _as_new_visitor(async_client_with_db)
    first_cookies = dict(async_client_with_db.cookies)
    second = _as_new_visitor(async_client_with_db)
    assert first != second

    guest = await UserService(async_db_session).get_user_by_email(GUEST_EMAIL)
    assert guest is not None
    rows = (await async_db_session.exec(RefreshToken.__table__.select())).all()
    assert {r.family_id for r in rows if r.user_id == guest.id} >= {first, second}
    assert {r.source for r in rows if r.user_id == guest.id} == {GUEST}

    # The second signs out alone: the first is still signed in.
    assert async_client_with_db.post("/api/v1/auth/logout").status_code == 200
    async_client_with_db.cookies.clear()
    async_client_with_db.cookies.update(first_cookies)
    assert async_client_with_db.get("/api/v1/auth/me").status_code == 200


@pytest.mark.queryspy(allow_n_plus_one=True)  # each visitor lists its own
async def test_a_guest_sees_and_ends_only_its_own_session(
    async_client_with_db: TestClient, async_db_session: AsyncSession
) -> None:
    other = _as_new_visitor(async_client_with_db)
    mine = _as_new_visitor(async_client_with_db)

    assert [s["id"] for s in async_client_with_db.get(SESSIONS).json()] == [mine]
    refused = async_client_with_db.delete(f"{SESSIONS}/{other}")
    assert refused.status_code == status.HTTP_404_NOT_FOUND
    everyone = async_client_with_db.delete(SESSIONS)
    assert everyone.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.queryspy(allow_n_plus_one=True)  # each visitor lists its own
async def test_a_guest_session_is_short(
    async_client_with_db: TestClient, async_db_session: AsyncSession
) -> None:
    sid = _as_new_visitor(async_client_with_db)
    (session,) = async_client_with_db.get(SESSIONS).json()
    assert session["id"] == sid
    lives = datetime.fromisoformat(session["expires_at"]) - datetime.fromisoformat(
        session["created_at"]
    )
    assert lives.total_seconds() <= settings.GUEST_SESSION_HOURS * 3600 + 60


async def test_an_address_may_start_only_so_many(
    async_client_with_db: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_GUEST_MAX", 1)
    _as_new_visitor(async_client_with_db)
    async_client_with_db.cookies.clear()
    again = async_client_with_db.post(GUEST_SIGN_IN)
    assert again.status_code == status.HTTP_429_TOO_MANY_REQUESTS


async def test_with_turnstile_on_a_failed_check_starts_nothing(
    async_client_with_db: TestClient,
    async_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_SITE_KEY", "site")
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "secret")

    async def refuse(token: str | None, ip: str | None) -> bool:
        return False

    monkeypatch.setattr(turnstile, "passed", refuse)
    response = async_client_with_db.post(GUEST_SIGN_IN, data={turnstile.FIELD: "x"})
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert await UserService(async_db_session).get_user_by_email(GUEST_EMAIL) is None


async def test_turnstile_is_off_without_its_keys() -> None:
    assert turnstile.enabled() is False
    assert await turnstile.passed(None, None) is True


async def test_a_guest_owns_by_its_session_and_a_user_by_id(
    async_db_session: AsyncSession, user_factory
) -> None:
    user = await user_factory()
    assert visitor(user, "s1") == str(user.id)
    guest = await guest_user(UserService(async_db_session))
    assert visitor(guest, "s1") == "guest:s1"


async def test_a_guest_is_no_member_of_the_shared_account(
    async_client_with_db: TestClient, async_db_session: AsyncSession
) -> None:
    """One click must not hand a stranger what a member may do: the user
    list, the account's profile, its orgs, its tokens."""
    _as_new_visitor(async_client_with_db)
    me = async_client_with_db.get("/api/v1/auth/me")
    assert me.status_code == 200
    renamed = async_client_with_db.patch(
        f"/api/v1/auth/users/{me.json()['id']}", json={"full_name": "Mine now"}
    )
    assert renamed.status_code == status.HTTP_403_FORBIDDEN
    assert async_client_with_db.get("/api/v1/auth/users").status_code == 403


async def test_a_guest_is_signed_out_to_every_optional_user_route(
    async_client_with_db: TestClient, async_db_session: AsyncSession
) -> None:
    """A page or a route that also serves anonymous callers sees no user in
    a guest (nothing keyed by the shared id), only its visitor."""
    from app.services.auth.deps import get_optional_user, get_visitor

    sid = _as_new_visitor(async_client_with_db)
    token = async_client_with_db.cookies.get(SESSION_COOKIE)
    users = UserService(async_db_session)
    assert await get_optional_user(token, users) is None
    assert await get_visitor(token, users) == guest_visitor(sid)


async def test_nobody_signs_up_as_the_guest(
    async_client_with_db: TestClient, async_db_session: AsyncSession
) -> None:
    async_client_with_db.cookies.clear()
    response = async_client_with_db.post(
        "/api/v1/auth/register",
        json={"email": GUEST_EMAIL, "full_name": "x", "password": "long-enough-1"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


async def test_a_guest_first_takes_no_admin_seat(
    async_db_session: AsyncSession,
) -> None:
    from sqlmodel import delete

    from app.models.user import User

    # A fresh deployment: none of the owners conftest seeds.
    await async_db_session.exec(delete(User))  # type: ignore[call-overload]
    users = UserService(async_db_session)
    guest = await guest_user(users)
    if not hasattr(guest, "role"):
        pytest.skip("no roles on this stack")
    operator = await users.create_user(
        UserCreate(email="op@example.com", full_name="Op", password="long-enough-1")
    )
    assert (guest.role, operator.role) == ("user", "admin")


async def test_the_guest_accounts_role_is_fixed(
    async_db_session: AsyncSession,
) -> None:
    """Every visitor holds it, so a role on it is a role for anyone: refused
    wherever a role is set (the admin API, ``auth promote``)."""
    users = UserService(async_db_session)
    guest = await guest_user(users)
    if not hasattr(guest, "role"):
        pytest.skip("no roles on this stack")
    with pytest.raises(ValueError, match="fixed"):
        await users.update_user(guest.id, role="admin")


async def test_a_deactivated_guest_account_closes_guest_sign_in(
    async_client_with_db: TestClient, async_db_session: AsyncSession
) -> None:
    users = UserService(async_db_session)
    guest = await guest_user(users)
    await users.update_user(guest.id, is_active=False)
    async_client_with_db.cookies.clear()
    response = async_client_with_db.post(GUEST_SIGN_IN)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"] == "guest_closed"
