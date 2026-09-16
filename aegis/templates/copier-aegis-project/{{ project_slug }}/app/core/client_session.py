"""The session-cookie half of ``APIClient``.

Separated because it is one subject and the client's own job is HTTP: the
jar, who may read and seed it, and telling the caller when the backend
rotates the refresh token. Everything here assumes the host class owns
``_client`` (an ``httpx.AsyncClient``), ``on_session_rotated`` and
``_last_refresh_cookie``.
"""

from __future__ import annotations

import inspect
from typing import Any

from httpx import CookieConflict

from app.core.log import logger

# The cookies the backend mints. Named here rather than imported from
# ``app.core.security`` so the client stays usable from contexts that do
# not pull in the auth service.
SESSION_COOKIE = "aegis_session"
REFRESH_COOKIE = "aegis_refresh"


class SessionCookieMixin:
    """Jar access, and the rotation hook a caller persists from."""

    _client: Any
    on_session_rotated: Any
    _last_refresh_cookie: str | None
    _in_refresh: bool
    _in_unauthorized: bool
    base_url: str

    def clear_cookies(self) -> None:
        """Drop every cookie in the jar. Used on logout to defang any stale session."""
        self._client.cookies.clear()
        self._last_refresh_cookie = None

    def get_cookie(self, name: str) -> str | None:
        """Read one cookie out of the jar, newest wins.

        A plain ``cookies.get`` RAISES when the jar holds two entries of
        the same name, which it does whenever a seeded cookie (no domain)
        meets the server's reply to it (host domain). Every caller here
        wants "the current one", and a raising accessor turned a working
        refresh into a silent sign-out.
        """
        try:
            return self._client.cookies.get(name)
        except CookieConflict:
            matches = [c.value for c in self._client.cookies.jar if c.name == name]
            return matches[-1] if matches else None

    def set_cookie(self, name: str, value: str, path: str = "/") -> None:
        """Seed a cookie into the jar - used to resume a persisted session."""
        self._client.cookies.set(name, value, path=path)

    def has_session_cookies(self) -> bool:
        """True when the jar still carries something worth trying."""
        return any(
            self._client.cookies.get(name) is not None
            for name in (SESSION_COOKIE, REFRESH_COOKIE)
        )

    async def refresh_session(self) -> bool:
        """Mint a new access token from the refresh cookie in the jar.

        Deliberately NOT gated on ``_in_unauthorized``, unlike the
        reactive path. A resume frequently runs inside that handler's
        scope - the 401 routes to /login, which asks whether the session
        is authenticated, which is where the resume lives - and the guard
        would report a refresh that never left the process as a refusal
        by the server. The recursion guard still applies.
        """
        if self._in_refresh:
            return False
        return await self._do_refresh()

    def _keep_only(self, name: str, value: str) -> None:
        """Evict every other cookie of this name from the jar.

        A seeded cookie and the server's rotation of it are two distinct
        jar entries - different domains - so the spent one lingers and
        both get sent on the next request. The backend reads a replayed
        token as reuse, so the loser has to go.
        """
        for cookie in list(self._client.cookies.jar):
            if cookie.name == name and cookie.value != value:
                self._client.cookies.jar.clear(
                    cookie.domain, cookie.path, cookie.name
                )

    async def _note_session_rotation(self) -> None:
        """Tell the caller when the refresh cookie changes value.

        Every path that mints one lands here - login, register, the OAuth
        callback, and ``/auth/refresh`` - because they all end in a
        response whose cookies the jar has just absorbed.
        """
        current = self._client.cookies.get(REFRESH_COOKIE)
        if current is None or current == self._last_refresh_cookie:
            return
        self._last_refresh_cookie = current
        if self.on_session_rotated is None:
            return
        try:
            result = self.on_session_rotated(current)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            # Persistence is a convenience; failing it must not fail the
            # request that happened to rotate the token.
            logger.debug(f"Session rotation callback failed: {exc}")

    async def _try_refresh(self) -> bool:
        """Attempt to mint a new access token via ``POST /auth/refresh``.

        Returns True if the server returned 200 (cookies are refreshed
        in the jar). Returns False on any other status or transport
        error. The ``_in_refresh`` flag prevents recursion if the
        refresh endpoint itself 401s. ``_in_unauthorized`` short-circuits
        when we're already inside the unauthorized-handler cleanup path
        (e.g. ``sign_out`` calling ``/auth/logout``) — no point trying
        to refresh into a session we're explicitly tearing down.
        """
        if self._in_refresh or self._in_unauthorized:
            return False
        return await self._do_refresh()

    async def _do_refresh(self) -> bool:
        """POST /auth/refresh and report whether the server accepted it."""
        self._in_refresh = True
        try:
            url = f"{self.base_url}/api/v1/auth/refresh"
            resp = await self._client.request("POST", url)
            if resp.status_code != 200:
                # Saying only "rejected" made a client-side refusal
                # indistinguishable from the server's, which cost a long
                # debugging session.
                logger.info(
                    "auth.refresh.refused",
                    status=resp.status_code,
                    sent_cookie=self._client.cookies.get(REFRESH_COOKIE) is not None,
                    body=resp.text[:200],
                )
            if resp.status_code == 200:
                rotated = resp.cookies.get(REFRESH_COOKIE)
                if rotated is not None:
                    self._keep_only(REFRESH_COOKIE, rotated)
                # A refresh rotates the token by design, and this call
                # bypasses ``_perform_request``, so it reports for itself.
                await self._note_session_rotation()
                return True
            return False
        except Exception as exc:
            # Never silent: swallowing this is what made a 200 refresh
            # indistinguishable from a rejected one.
            logger.warning("auth.refresh.failed", error=str(exc))
            return False
        finally:
            self._in_refresh = False
