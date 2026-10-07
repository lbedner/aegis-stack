"""The auth endpoints' rate limits read their settings on each check, so a
limit saved in the Overseer applies once the process has booted."""

from fastapi import HTTPException, Request
import pytest

from app.components.backend.security import rate_limit
from app.components.backend.security.rate_limit import RateLimiter
from app.core.config import settings


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("10.0.0.1", 1)})


def _limiter() -> RateLimiter:
    return RateLimiter("RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW")


def test_a_limit_changed_after_import_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = _limiter()
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_MAX", 1)
    limiter.check(_request())
    with pytest.raises(HTTPException) as refused:
        limiter.check(_request())
    assert refused.value.status_code == 429


def test_a_bucket_can_be_any_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_MAX", 1)
    limiter = _limiter()
    limiter.check_key("user:1")
    limiter.check_key("user:2")
    with pytest.raises(HTTPException):
        limiter.check_key("user:1")


def test_buckets_whose_window_passed_are_let_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key never seen again must not hold memory for the life of the
    process: one-off callers (or keys) would grow it without end."""
    monkeypatch.setattr(rate_limit, "SWEEP_AT", 2)
    clock = iter([0.0, 1.0, 10_000.0])
    monkeypatch.setattr(rate_limit.time, "time", lambda: next(clock))
    limiter = _limiter()
    for key in ("a", "b", "c"):
        limiter.check_key(key)
    assert set(limiter._requests) == {"c"}
