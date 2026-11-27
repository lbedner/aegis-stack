"""The one way a test signs a request in by token: the header an API
client sends for ``email``'s access token."""

from app.core.security import create_access_token


def bearer(email: str) -> dict[str, str]:
    """An ``Authorization`` header signed in as ``email``."""
    return {"Authorization": f"Bearer {create_access_token(data={'sub': email})}"}
