"""Simple in-memory rate limiter for auth endpoints.

The ``RateLimiter`` class and its three pre-configured instances are the
implementation. The ``*_rate_limit`` callables at the bottom of this
module are thin ``Depends``-able wrappers; route handlers import those
from ``app.components.backend.api.deps`` rather than reaching in here
directly.
"""

import time

from app.core.config import settings
from fastapi import HTTPException, Request, status


def get_client_ip(request: Request) -> str | None:
    """The client's address: behind a trusted proxy, the one it forwarded
    (``TrustedProxyMiddleware`` has already rewritten it). ``None`` when
    there is none (a session's IP column is nullable)."""
    return request.client.host if request.client else None


def get_session_metadata(request: Request) -> dict[str, str | None]:
    """Pull the columns needed for a refresh-token session row off
    ``request``: ``user_agent`` (trimmed to the column width) and
    ``ip`` (honoring proxy headers per :func:`get_client_ip`).
    Issue #633.
    """
    ua = request.headers.get("user-agent")
    return {
        "user_agent": ua[:512] if ua else None,
        "ip": get_client_ip(request),
    }


# Buckets held before those whose window has passed are let go: a key seen
# once (a one-off caller) would otherwise stay for the life of the process.
SWEEP_AT = 10_000


class RateLimiter:
    """In-memory rate limiter using sliding window. Its limit and window are
    the named settings, read on each check, so a value saved in the Overseer
    applies once the process has booted."""

    def __init__(self, max_setting: str, window_setting: str) -> None:
        self.max_setting = max_setting
        self.window_setting = window_setting
        self._requests: dict[str, list[float]] = {}
        self._sweep_at = SWEEP_AT

    @property
    def max_requests(self) -> int:
        return int(getattr(settings, self.max_setting))

    @property
    def window_seconds(self) -> int:
        return int(getattr(settings, self.window_setting))

    def check(self, request: Request) -> None:
        """Check the caller's rate limit; an unknown address is one bucket.
        Raises 429 if exceeded."""
        self.check_key(get_client_ip(request) or "unknown")

    def check_key(self, key: str) -> None:
        """Check the limit of the bucket ``key``, for a limit on something
        other than the caller (a user id). Raises 429 if exceeded."""
        now = time.time()
        cutoff = now - self.window_seconds
        if len(self._requests) >= self._sweep_at:
            self._sweep(cutoff)
        recent = [t for t in self._requests.get(key, []) if t > cutoff]
        self._requests[key] = recent
        if len(recent) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )
        recent.append(now)

    def _sweep(self, cutoff: float) -> None:
        """Let go of every bucket whose window has passed; the next sweep
        waits for twice what is left, so a busy process sweeps rarely."""
        self._requests = {
            key: times
            for key, times in self._requests.items()
            if times and times[-1] > cutoff
        }
        self._sweep_at = max(SWEEP_AT, 2 * len(self._requests))

    def reset(self) -> None:
        """Clear all rate limit state. Useful for testing."""
        self._requests.clear()


# Shared instances for auth endpoints
login_limiter = RateLimiter("RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW")
register_limiter = RateLimiter("RATE_LIMIT_REGISTER_MAX", "RATE_LIMIT_REGISTER_WINDOW")
password_reset_limiter = RateLimiter(
    "RATE_LIMIT_REGISTER_MAX", "RATE_LIMIT_REGISTER_WINDOW"
)
# Separate bucket for verification-email resends. Its own dedicated
# settings keep it from inheriting the tighter register limit — this
# is a user-facing button, not a signup path, and legit retries
# shouldn't feel punishing.
resend_verification_limiter = RateLimiter(
    "RATE_LIMIT_RESEND_VERIFICATION_MAX", "RATE_LIMIT_RESEND_VERIFICATION_WINDOW"
)


def login_rate_limit(request: Request) -> None:
    """FastAPI dependency: enforce the login rate limit."""
    login_limiter.check(request)


def register_rate_limit(request: Request) -> None:
    """FastAPI dependency: enforce the registration rate limit."""
    register_limiter.check(request)


def password_reset_rate_limit(request: Request) -> None:
    """FastAPI dependency: enforce the password-reset rate limit."""
    password_reset_limiter.check(request)


def resend_verification_rate_limit(request: Request) -> None:
    """FastAPI dependency: enforce the resend-verification rate limit."""
    resend_verification_limiter.check(request)
