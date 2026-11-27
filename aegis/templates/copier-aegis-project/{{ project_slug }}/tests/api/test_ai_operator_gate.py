"""The AI service's operator routes are an admin's: the agent registry
(``analytics.py``: a prompt rides in every turn of its agent), what the
models cost across users, and the memory API (``memory.py``: a context
module's text rides in every turn of every agent that reads it, and the
saved facts are any user's by the ``user_id`` asked for). A signed-in
user who is not an admin reaches none of it."""


from fastapi.testclient import TestClient
import pytest

from app.core.config import settings

# Without the auth service there is no admin to tell apart: the operator
# is whoever reaches the app (``get_admin_reader``).
# Without auth there is no session to read a user from: admins need sign-in.
bearer = pytest.importorskip("tests._bearer").bearer

ROUTES = [
    ("GET", "/api/v1/ai/agents"),
    ("PATCH", "/api/v1/ai/agents/assistant"),
    ("GET", "/api/v1/ai/usage/stats"),
    ("GET", "/api/v1/ai/sentiment/stats"),
    ("GET", "/api/v1/ai/context-modules"),
    ("PATCH", "/api/v1/ai/context-modules/app_map"),
    ("GET", "/api/v1/ai/context-modules/app_map/preview"),
    ("GET", "/api/v1/ai/user-memory"),
    ("PATCH", "/api/v1/ai/user-memory/0"),
    ("DELETE", "/api/v1/ai/user-memory/0"),
]


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "ADMIN_USER_EMAILS", ["owner1@test.local"])


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_a_member_reaches_none_of_it(
    async_client_with_db: TestClient, method: str, path: str
) -> None:
    response = async_client_with_db.request(
        method, path, json={}, headers=bearer("owner2@test.local")
    )
    assert response.status_code == 403, (method, path, response.status_code)


@pytest.mark.parametrize("path", ["/api/v1/ai/context-modules", "/api/v1/ai/agents"])
def test_an_admin_still_reads_them(async_client_with_db: TestClient, path: str) -> None:
    response = async_client_with_db.get(path, headers=bearer("owner1@test.local"))
    assert response.status_code == 200, response.text
