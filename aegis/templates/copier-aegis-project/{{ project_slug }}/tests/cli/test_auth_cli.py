"""``auth create-user``: a real account, its password asked (hidden, twice),
never an option and never printed."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.cli import auth as auth_cli
from app.core.config import settings
from app.models.user import User, UserCreate
from tests._cli import invoke

PASSWORD = "a-long-passphrase"


class Users:
    """The ``UserService`` the command uses, holding what it creates."""

    made: dict[str, UserCreate]

    def __init__(self, session: Any) -> None:
        pass

    async def get_user_by_email(self, email: str) -> Any:
        return self.made.get(email)

    async def create_user(self, data: UserCreate) -> Any:
        self.made[data.email] = data
        # The real model: a stand-in lacks fields a stack adds (``role``).
        return User(id=1, email=data.email, hashed_password="!")


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> dict[str, UserCreate]:
    @asynccontextmanager
    async def session() -> AsyncIterator[None]:
        yield None

    Users.made = {}
    monkeypatch.setattr(auth_cli, "UserService", Users)
    monkeypatch.setattr(auth_cli, "get_async_session", session)
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "ADMIN_USER_EMAILS", ["me@example.com"])
    return Users.made


def test_create_user_asks_the_password_twice_and_never_prints_it(
    made: dict[str, UserCreate],
) -> None:
    result = invoke(
        ["auth", "create-user", "--email", "me@example.com"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert made["me@example.com"].password == PASSWORD
    assert PASSWORD not in result.output
    assert "me@example.com" in result.output
    assert "ADMIN_USER_EMAILS" not in result.output  # already an admin


def test_create_user_says_how_to_make_it_an_admin(
    made: dict[str, UserCreate],
) -> None:
    result = invoke(
        ["auth", "create-user", "--email", "other@example.com"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    assert "ADMIN_USER_EMAILS" in result.output


def test_create_user_refuses_an_email_already_taken(
    made: dict[str, UserCreate],
) -> None:
    made["me@example.com"] = UserCreate(email="me@example.com", password=PASSWORD)
    result = invoke(
        ["auth", "create-user", "--email", "me@example.com"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
    )
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_create_user_refuses_a_short_password(made: dict[str, UserCreate]) -> None:
    result = invoke(
        ["auth", "create-user", "--email", "me@example.com"], input="short\nshort\n"
    )
    assert result.exit_code == 1
    assert not made
