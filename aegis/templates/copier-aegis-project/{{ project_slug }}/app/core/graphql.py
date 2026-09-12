"""A small GraphQL-over-HTTP client.

GraphQL is one POST shape - ``{"query", "variables"}`` to a single
endpoint - so this stays deliberately thin: it owns the connection pool,
the request framing, and the two things every caller would otherwise get
wrong. A server reports resolver failures with a **200** and an
``errors`` array, and a transport failure surfaces as an ``httpx``
exception type callers should not have to know about. Both become typed
errors here.

Endpoint-agnostic on purpose. An API-specific client (GitHub, ...)
subclasses this and supplies the endpoint, auth headers, and whatever
paging or rate-limit behaviour that API needs.

``transport`` is the injection seam: tests pass ``httpx.MockTransport``
and never monkeypatch ``httpx``; production passes nothing.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx


class GraphQLError(Exception):
    """The server answered, but the response carried an ``errors`` array."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        messages = "; ".join(str(e.get("message", e)) for e in errors) or "unknown"
        super().__init__(f"GraphQL error: {messages}")


class GraphQLHTTPError(Exception):
    """The request never produced a GraphQL response.

    ``status`` is the HTTP status for a non-2xx reply and ``None`` when the
    transport itself failed (connection refused, timeout). ``body`` is the
    response text or the transport error message.
    """

    def __init__(self, status: int | None, body: str) -> None:
        self.status = status
        self.body = body
        where = f"HTTP {status}" if status is not None else "transport error"
        super().__init__(f"GraphQL request failed ({where}): {body[:200]}")


class GraphQLClient:
    """One endpoint, one connection pool, one ``query()``."""

    def __init__(
        self,
        endpoint: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint
        self._http = httpx.AsyncClient(
            headers=headers or {},
            timeout=timeout,
            transport=transport,
        )

    async def query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """POST ``query`` and return its ``data``.

        Always sends ``variables`` as an object: a missing key is accepted
        everywhere, but ``null`` is rejected by some servers.
        """
        try:
            response = await self._http.post(
                self.endpoint,
                json={"query": query, "variables": variables or {}},
            )
        except httpx.HTTPError as exc:
            raise GraphQLHTTPError(None, str(exc)) from exc

        if response.status_code // 100 != 2:
            raise GraphQLHTTPError(response.status_code, response.text)

        payload = response.json()
        errors = payload.get("errors")
        if errors:
            raise GraphQLError(errors)
        return payload.get("data") or {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> GraphQLClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
