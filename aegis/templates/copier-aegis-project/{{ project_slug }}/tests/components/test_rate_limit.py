"""The auth endpoints' rate limits read their settings on each check, so a
limit saved in the Overseer applies once the process has booted."""

from fastapi import HTTPException, Request
import pytest

from app.components.backend.security.rate_limit import login_limiter
from app.core.config import settings


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("10.0.0.1", 1)})


def test_a_limit_changed_after_import_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    login_limiter.reset()
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_MAX", 1)
    login_limiter.check(_request())
    with pytest.raises(HTTPException) as refused:
        login_limiter.check(_request())
    assert refused.value.status_code == 429
    login_limiter.reset()
