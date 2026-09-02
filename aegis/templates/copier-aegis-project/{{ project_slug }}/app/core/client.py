"""
Shared HTTP client for internal API calls.

Used by frontend components to call backend API endpoints. Provides
consistent base URL, timeout, error handling, JSON parsing, persistent
session cookies, and an unauthorized callback for triggering
session-level logout.

This is the **One True Client** for the Aegis frontend — every server
call from a view, modal, or service should go through it. Raw
``httpx.AsyncClient`` use outside this module is a code smell.

Auth model
----------
The client holds a long-lived ``httpx.AsyncClient`` whose cookie jar
persists across requests. When the backend issues ``Set-Cookie:
aegis_session=...`` (e.g. from ``/auth/token``, ``/auth/register``,
or the OAuth callback), it lands in this jar and is automatically
sent back on every subsequent call. Logout drops the cookie via
``/auth/logout`` *and* clears the jar locally.

Each Flet session gets its own ``APIClient`` (constructed in
``init_session_state``) so cookie jars do not bleed across users.
The ``aclose()`` method releases the underlying connection pool;
call it from ``on_disconnect`` or ``clear_session_state``.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import inspect
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.log import logger

UnauthorizedHandler = Callable[[], None] | Callable[[], Awaitable[None]]


class APIClient:
    """HTTP client for internal API calls.

    Cookie jar-backed session: the underlying ``httpx.AsyncClient`` is
    created once and kept alive for the life of the Flet session.
    Anything the backend stores in cookies (notably ``aegis_session``)
    rides along on every subsequent call.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 10.0,
        on_unauthorized: UnauthorizedHandler | None = None,
    ) -> None:
        self.base_url = base_url or f"http://localhost:{settings.PORT}"
        self.timeout = timeout
        self.on_unauthorized = on_unauthorized
        # Human-readable reason for the most recent failed request, None
        # after a success. The request methods return None on ANY error
        # (details go to the log), which leaves UI callers unable to say
        # what failed - this carries the same detail to the surface that
        # just got None back (e.g. the loading overlay's error panel).
        self.last_error: str | None = None
        # Re-entry guard. If ``on_unauthorized`` itself triggers another
        # 401 (the canonical case: ``sign_out`` calls ``/auth/logout``,
        # which 401s when the cookie is already stale — which is exactly
        # when the handler fires), we'd recurse forever. The flag stays
        # True for the lifetime of the outermost handler invocation so
        # nested 401s short-circuit.
        self._in_unauthorized = False
        # Re-entry guard for the refresh-on-401 retry layer. Stops
        # ``/auth/refresh`` itself from triggering a refresh attempt if
        # it returns 401, which would otherwise recurse.
        self._in_refresh = False
        # ``follow_redirects`` lets the OAuth callback chain (303 → /)
        # work end-to-end if a server-side caller ever uses it. Cookie
        # jar is built into ``httpx.AsyncClient``.
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )
        # Opt-in GET cache (see ``get``'s ``cache_ttl``). Key is
        # endpoint+params; value is (monotonic deadline, parsed body).
        # ``_get_inflight`` coalesces concurrent identical reads onto one
        # request - a dashboard opening every tab fires the same reference
        # reads many times in the same instant.
        self._get_cache: dict[str, tuple[float, dict | list | None]] = {}
        self._get_inflight: dict[str, asyncio.Task[dict | list | None]] = {}

    async def aclose(self) -> None:
        """Release the underlying connection pool. Call on session teardown."""
        await self._client.aclose()

    def clear_cookies(self) -> None:
        """Drop every cookie in the jar. Used on logout to defang any stale session."""
        self._client.cookies.clear()

    async def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        cache_ttl: float | None = None,
    ) -> dict | list | None:
        """GET request. Returns parsed JSON or None on error.

        ``cache_ttl`` opts this read into the client's GET cache: the
        parsed body is reused for that many seconds, and concurrent
        identical reads share one request in flight. Any write through
        this client drops the whole cache, so a caller can never read its
        own write stale. Reserve it for reference data many surfaces read
        at once (account lists, category options) - never for anything
        whose params make it unique per view anyway.
        """
        if cache_ttl is None:
            return await self._request("GET", endpoint, params=params)
        return await self._cached_get(endpoint, params, cache_ttl)

    async def _cached_get(
        self, endpoint: str, params: dict[str, Any] | None, ttl: float
    ) -> dict | list | None:
        key = f"{endpoint}?{sorted((params or {}).items())!r}"
        hit = self._get_cache.get(key)
        if hit is not None and time.monotonic() < hit[0]:
            return hit[1]

        inflight = self._get_inflight.get(key)
        if inflight is None:

            async def fetch() -> dict | list | None:
                try:
                    result = await self._request("GET", endpoint, params=params)
                    if result is not None:
                        # Errors return None and are never cached - a
                        # blip must not blank a surface for a whole TTL.
                        self._get_cache[key] = (time.monotonic() + ttl, result)
                    return result
                finally:
                    self._get_inflight.pop(key, None)

            inflight = asyncio.create_task(fetch())
            self._get_inflight[key] = inflight
        return await inflight

    def _invalidate_get_cache(self) -> None:
        """Drop every cached GET. Called after any write through this
        client: reference data is cheap to refetch and a stale read after
        the user's own edit is a visible bug."""
        self._get_cache.clear()

    async def post(
        self,
        endpoint: str,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict | list | None:
        """POST request with a JSON body. Returns parsed JSON or None on error.

        ``timeout`` overrides the client-wide budget for this one call (for
        endpoints that do real work inline, e.g. the analyst note waits on a
        local model).
        """
        return await self._request("POST", endpoint, json=json, timeout=timeout)

    async def post_form(
        self, endpoint: str, data: dict[str, str]
    ) -> dict | list | None:
        """
        POST request with a form-encoded body.

        Used for endpoints that consume ``application/x-www-form-urlencoded``
        — most notably FastAPI's ``OAuth2PasswordRequestForm`` at
        ``/api/v1/auth/token``.
        """
        return await self._request("POST", endpoint, form_data=data)

    async def post_multipart(
        self,
        endpoint: str,
        files: dict[str, tuple[str, bytes, str]],
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict | list | None:
        """
        POST a ``multipart/form-data`` body.

        ``files`` shape matches httpx: ``{field_name: (filename, bytes, mime)}``.
        ``params`` are appended as the URL query string (used for things like
        ``?on_conflict=skip``). Cookies + 401 → ``on_unauthorized`` are
        handled the same as the JSON-bodied methods. ``Content-Type`` is
        **not** set manually — httpx infers ``multipart/form-data;
        boundary=…`` from ``files=``.

        ``timeout`` overrides the client-wide budget for this one call:
        uploads that trigger server-side processing (the finance file
        import runs its reconciliation rules inline) legitimately outlive
        the 10s default.
        """
        return await self._request(
            "POST", endpoint, files=files, params=params, timeout=timeout
        )

    async def get_bytes(self, endpoint: str) -> bytes | None:
        """A binary body (a page image); the standard path, body undecoded."""
        result = await self._request("GET", endpoint, raw=True)
        return result if isinstance(result, bytes) else None

    async def put(
        self, endpoint: str, json: dict[str, Any] | None = None
    ) -> dict | list | None:
        """PUT request. Returns parsed JSON or None on error."""
        return await self._request("PUT", endpoint, json=json)

    async def patch(
        self, endpoint: str, json: dict[str, Any] | None = None
    ) -> dict | list | None:
        """PATCH request with a JSON body. Returns parsed JSON or None on error."""
        return await self._request("PATCH", endpoint, json=json)

    async def delete(self, endpoint: str) -> dict | list | None:
        """DELETE request. Returns parsed JSON or None on error."""
        return await self._request("DELETE", endpoint)

    async def request_with_status(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        form_data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        _retry_on_401: bool = True,
    ) -> tuple[int, dict | list | None]:
        """
        Status-aware variant: returns ``(status_code, body)`` instead of
        raising or hiding the status code.

        Use this when the caller needs to branch on specific status codes
        (e.g. 204 success vs 403 forbidden, or 200 vs 400 validation).
        Cookies are still attached and 401 still fires
        ``on_unauthorized`` — the caller just additionally sees the code.

        Returns:
            ``(0, None)`` on network/timeout errors;
            ``(status_code, parsed_json or None)`` otherwise.
        """
        if method != "GET":
            self._invalidate_get_cache()
        url = f"{self.base_url}{endpoint}"
        headers: dict[str, str] = {}
        if form_data is not None and files is None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json,
                data=form_data,
                files=files,
                headers=headers,
            )
            if response.status_code == 401:
                if (
                    _retry_on_401
                    and endpoint != "/api/v1/auth/refresh"
                    and await self._try_refresh()
                ):
                    return await self.request_with_status(
                        method,
                        endpoint,
                        params=params,
                        json=json,
                        form_data=form_data,
                        files=files,
                        _retry_on_401=False,
                    )
                await self._emit_unauthorized()
            if response.status_code == 204 or not response.content:
                return response.status_code, None
            try:
                return response.status_code, response.json()
            except Exception:
                return response.status_code, None
        except httpx.TimeoutException:
            logger.error("api_client.timeout", url=url, method=method)
        except httpx.ConnectError:
            logger.error("api_client.connect_error", url=url, method=method)
        except Exception as e:
            logger.error("api_client.error", url=url, method=method, error=str(e))
        return 0, None

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> AsyncIterator[httpx.Response]:
        """
        Open a streaming response (used for SSE).

        Yields the raw ``httpx.Response`` so the caller can iterate via
        ``response.aiter_lines()`` or ``response.aiter_bytes()``. Cookies
        are attached automatically; a 401 fires ``on_unauthorized``.

        Example::

            async with api_client.stream("GET", "/events/stream") as resp:
                async for line in resp.aiter_lines():
                    ...
        """
        url = f"{self.base_url}{endpoint}"
        async with self._client.stream(method, url, **kwargs) as response:
            if response.status_code == 401:
                await self._emit_unauthorized()
            yield response

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
        self._in_refresh = True
        try:
            url = f"{self.base_url}/api/v1/auth/refresh"
            resp = await self._client.request("POST", url)
            return resp.status_code == 200
        except Exception:
            return False
        finally:
            self._in_refresh = False

    async def _emit_unauthorized(self) -> None:
        if self.on_unauthorized is None or self._in_unauthorized:
            return
        self._in_unauthorized = True
        try:
            result = self.on_unauthorized()
            if inspect.isawaitable(result):
                await result
        finally:
            self._in_unauthorized = False

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        form_data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        timeout: float | None = None,
        raw: bool = False,
        _retry_on_401: bool = True,
    ) -> Any:
        if method == "GET":
            return await self._perform_request(
                method,
                endpoint,
                params=params,
                json=json,
                form_data=form_data,
                files=files,
                timeout=timeout,
                raw=raw,
                _retry_on_401=_retry_on_401,
            )
        try:
            return await self._perform_request(
                method,
                endpoint,
                params=params,
                json=json,
                form_data=form_data,
                files=files,
                timeout=timeout,
                raw=raw,
                _retry_on_401=_retry_on_401,
            )
        finally:
            # AFTER the write, not before: a cached read racing a write
            # could re-cache the pre-write body for a whole TTL.
            self._invalidate_get_cache()

    async def _perform_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        form_data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        timeout: float | None = None,
        raw: bool = False,
        _retry_on_401: bool = True,
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        headers: dict[str, str] = {}
        if form_data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        # NOTE: do NOT set Content-Type for ``files=`` — httpx generates
        # the multipart boundary itself. Setting it here would clobber it.
        # Per-request timeout only when asked: ``timeout=None`` at the httpx
        # layer means "no timeout at all", which is never what a UI wants.
        extra: dict[str, Any] = {} if timeout is None else {"timeout": timeout}
        try:
            response = await self._client.request(
                method,
                url,
                params=params,
                json=json,
                data=form_data,
                files=files,
                headers=headers,
                **extra,
            )
            response.raise_for_status()
            self.last_error = None
            if response.status_code == 204:
                return None
            return response.content if raw else response.json()
        except httpx.TimeoutException:
            budget = timeout if timeout is not None else self.timeout
            self.last_error = f"{method} {endpoint} timed out after {budget:g}s"
            logger.error("api_client.timeout", url=url, method=method)
        except httpx.HTTPStatusError as e:
            detail = self._response_detail(e.response)
            self.last_error = (
                f"{method} {endpoint} failed with HTTP {e.response.status_code}"
                + (f": {detail}" if detail else "")
            )
            if e.response.status_code == 401:
                # Refresh-on-401: silently mint a new access token and
                # retry the original request once. Skip when this call
                # was itself a retry, when the failing endpoint is the
                # refresh endpoint, or when we're already inside a
                # refresh round-trip — see ``_try_refresh``.
                if (
                    _retry_on_401
                    and endpoint != "/api/v1/auth/refresh"
                    and await self._try_refresh()
                ):
                    return await self._request(
                        method,
                        endpoint,
                        params=params,
                        json=json,
                        form_data=form_data,
                        files=files,
                        timeout=timeout,
                        raw=raw,
                        _retry_on_401=False,
                    )
                await self._emit_unauthorized()
            logger.error(
                "api_client.http_error",
                url=url,
                method=method,
                status_code=e.response.status_code,
            )
        except httpx.ConnectError:
            self.last_error = f"Could not connect to the API ({method} {endpoint})"
            logger.error("api_client.connect_error", url=url, method=method)
        except Exception as e:
            self.last_error = f"{method} {endpoint} failed: {e}"
            logger.error("api_client.error", url=url, method=method, error=str(e))
        return None

    @staticmethod
    def _response_detail(response: httpx.Response) -> str:
        """Best-effort human-readable detail from an error response body.

        FastAPI puts the real message in ``{"detail": ...}``; anything else
        falls back to a truncated body, or empty when unreadable.
        """
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("detail"):
                return str(payload["detail"])
        except Exception:
            pass
        text = getattr(response, "text", "")
        return text[:300] if isinstance(text, str) else ""


def get_api_client() -> APIClient:
    """Dependency provider for APIClient."""
    return APIClient()
