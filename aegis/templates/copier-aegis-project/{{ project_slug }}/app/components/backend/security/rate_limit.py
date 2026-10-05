"""Simple in-memory rate limiter for auth endpoints.

The ``RateLimiter`` class and its three pre-configured instances are the
implementation. The ``*_rate_limit`` callables at the bottom of this
module are thin ``Depends``-able wrappers; route handlers import those
from ``app.components.backend.api.deps`` rather than reaching in here
directly.
"""

import time
from collections import defaultdict

from app.core.config import settings
from fastapi import HTTPException, Request, status


def get_client_ip(
    request: Request, *, trust_proxy_headers: bool | None = None
) -> str | None:
    """Resolve the real client IP for ``request``.

    Honors ``X-Forwarded-For`` when ``trust_proxy_headers`` is True;
    defaults to ``settings.TRUST_PROXY_HEADERS``. Returns ``None`` if
    neither a forwarded header nor a direct client address is
    available — refresh-token session columns are nullable, so a
    missing IP is a valid value there.

    Distinct from :meth:`RateLimiter._get_client_ip` only in its
    fallback: the limiter wants ``"unknown"`` (a real bucket key) when
    the IP can't be resolved; the session-metadata path wants
    ``None`` so a missing value persists as NULL instead of the
    literal string ``"unknown"``.
    """
    if trust_proxy_headers is None:
        trust_proxy_headers = settings.TRUST_PROXY_HEADERS
    if trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
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


class RateLimiter:
    """In-memory rate limiter using sliding window. Its limit and window are
    the named settings, read on each check, so a value saved in the Overseer
    applies once the process has booted (as does ``TRUST_PROXY_HEADERS``)."""

    def __init__(self, max_setting: str, window_setting: str) -> None:
        self.max_setting = max_setting
        self.window_setting = window_setting
        self._requests: dict[str, list[float]] = defaultdict(list)

    @property
    def max_requests(self) -> int:
        return int(getattr(settings, self.max_setting))

    @property
    def window_seconds(self) -> int:
        return int(getattr(settings, self.window_setting))

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP from request. The limiter wants a real bucket
        key even when the IP can't be resolved, so this falls back to
        the literal ``"unknown"`` rather than ``None``."""
        ip = get_client_ip(request)
        return ip if ip is not None else "unknown"

    def _cleanup(self, key: str) -> None:
        """Remove expired timestamps."""
        cutoff = time.time() - self.window_seconds
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

    def check(self, request: Request) -> None:
        """Check rate limit. Raises 429 if exceeded."""
        ip = self._get_client_ip(request)
        self._cleanup(ip)

        if len(self._requests[ip]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )

        self._requests[ip].append(time.time())

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
