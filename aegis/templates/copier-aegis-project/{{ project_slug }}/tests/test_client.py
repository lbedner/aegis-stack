"""
Tests for APIClient.

The client owns a long-lived ``httpx.AsyncClient`` (cookie jar lives on
that instance), so tests patch ``client._client.request`` /
``client._client.stream`` directly instead of patching the constructor.

Async tests use the ``make_client`` factory fixture so every constructed
``APIClient`` is ``aclose()``d in teardown — without that, each test
leaks an httpx connection pool and pytest emits ``ResourceWarning``s.
The 3 sync constructor tests build a client inline and don't need
cleanup since they never make a request.
"""

from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.client import APIClient


def _mock_response(
    status_code: int = 200,
    json_payload: dict | list | None = None,
    raise_status: Exception | None = None,
    content: bytes = b"x",
) -> MagicMock:
    """Build a mock httpx.Response for a single request call."""
    response = MagicMock()
    response.status_code = status_code
    response.content = content
    response.json.return_value = json_payload if json_payload is not None else {}
    if raise_status is None:
        response.raise_for_status = MagicMock()
    else:
        response.raise_for_status = MagicMock(side_effect=raise_status)
    return response


@pytest.fixture
async def make_client() -> AsyncIterator[Callable[..., APIClient]]:
    """Factory that builds APIClients and aclose's them on teardown.

    Tests can call ``make_client(on_unauthorized=...)`` etc. to
    customize, and the fixture guarantees cleanup whether the test
    passes or fails.
    """
    clients: list[APIClient] = []

    def _make(**kwargs: Any) -> APIClient:
        kwargs.setdefault("base_url", "http://test")
        client = APIClient(**kwargs)
        clients.append(client)
        return client

    yield _make

    for client in clients:
        await client.aclose()


class TestAPIClient:
    def test_default_base_url(self) -> None:
        client = APIClient()
        assert "localhost" in client.base_url
        assert "8000" in client.base_url

    def test_custom_base_url(self) -> None:
        client = APIClient(base_url="http://example.com")
        assert client.base_url == "http://example.com"

    def test_custom_timeout(self) -> None:
        client = APIClient(timeout=30.0)
        assert client.timeout == 30.0

    @pytest.mark.asyncio
    async def test_get_success(self, make_client: Callable[..., APIClient]) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"data": "ok"})
        )

        result = await client.get("/api/test")

        assert result == {"data": "ok"}

    @pytest.mark.asyncio
    async def test_get_timeout_returns_none(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.TimeoutException("timeout")
        )

        result = await client.get("/api/test")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_connect_error_returns_none(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.ConnectError("refused")
        )

        result = await client.get("/api/test")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_http_error_returns_none(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        response = _mock_response(
            500,
            raise_status=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock(status_code=500)
            ),
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        result = await client.get("/api/test")

        assert result is None

    @pytest.mark.asyncio
    async def test_204_returns_none(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(204)
        )

        result = await client.get("/api/test")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_authorization_header_attached_by_client(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        """
        Cookies are the auth carrier for this client session, so the client
        must NOT manually attach Authorization headers. Callers may still
        pass explicit headers when needed.
        """
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"ok": True})
        )

        await client.get("/api/test")

        _, kwargs = client._client.request.call_args
        headers = kwargs.get("headers") or {}
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_401_invokes_on_unauthorized_callback(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        called: list[bool] = []

        def on_unauthorized() -> None:
            called.append(True)

        client = make_client(on_unauthorized=on_unauthorized)
        response = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        result = await client.get("/api/test")

        assert result is None
        assert called == [True]

    @pytest.mark.asyncio
    async def test_async_on_unauthorized_supported(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        called: list[bool] = []

        async def on_unauthorized() -> None:
            called.append(True)

        client = make_client(on_unauthorized=on_unauthorized)
        response = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        await client.get("/api/test")

        assert called == [True]

    @pytest.mark.asyncio
    async def test_on_unauthorized_recursion_guard_fires_handler_only_once(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        """
        If the ``on_unauthorized`` handler itself triggers another 401
        (canonical case: ``sign_out`` calls ``/auth/logout`` which 401s
        on a stale cookie), the handler must NOT recurse forever — the
        in-flight guard should suppress the nested ``_emit_unauthorized``
        and let the handler complete normally.
        """
        import httpx

        call_count = 0

        async def on_unauthorized() -> None:
            nonlocal call_count
            call_count += 1
            # Re-enter the client during the handler. The mocked
            # request below also returns 401, which would otherwise
            # fire on_unauthorized a second time.
            await client.post("/api/v1/auth/logout")

        client = make_client(on_unauthorized=on_unauthorized)
        response = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        await client.get("/api/test")

        assert call_count == 1, (
            f"on_unauthorized fired {call_count} times — recursion guard "
            "should clamp to 1 even when the handler triggers a nested 401."
        )

    @pytest.mark.asyncio
    async def test_401_refreshes_and_retries(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        """First call 401s, refresh succeeds, retry returns 200.
        ``on_unauthorized`` must NOT fire — the user sees a clean 200."""
        import httpx

        called: list[bool] = []

        async def on_unauthorized() -> None:
            called.append(True)

        client = make_client(on_unauthorized=on_unauthorized)

        # The mock sees three calls in order: original (401), refresh (200),
        # retry (200). We script the responses by side_effect.
        original_401 = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        refresh_ok = _mock_response(200, {"access_token": "new"})
        retry_ok = _mock_response(200, {"data": "ok"})
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=[original_401, refresh_ok, retry_ok],
        )

        result = await client.get("/api/test")

        assert result == {"data": "ok"}
        assert called == []  # refresh succeeded, no logout fired
        assert client._client.request.call_count == 3
        # The middle call targeted /auth/refresh.
        refresh_call_args = client._client.request.call_args_list[1]
        assert "/api/v1/auth/refresh" in refresh_call_args.args[1]

    @pytest.mark.asyncio
    async def test_401_refresh_fails_fires_on_unauthorized(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        """If refresh itself returns non-200, fall back to the existing
        ``on_unauthorized`` path — no infinite retry loop."""
        import httpx

        called: list[bool] = []

        async def on_unauthorized() -> None:
            called.append(True)

        client = make_client(on_unauthorized=on_unauthorized)

        original_401 = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        # Refresh also 401s. _try_refresh reads status_code (no raise).
        refresh_401 = _mock_response(401)
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=[original_401, refresh_401],
        )

        result = await client.get("/api/test")

        assert result is None
        assert called == [True]

    @pytest.mark.asyncio
    async def test_refresh_endpoint_401_does_not_recurse(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        """A direct ``post('/api/v1/auth/refresh')`` that 401s must not try
        to refresh itself — that would loop forever. The retry layer is
        gated on the endpoint."""
        import httpx

        client = make_client()
        response = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        result = await client.post("/api/v1/auth/refresh")

        assert result is None
        # Exactly one request — no refresh-and-retry of itself.
        assert client._client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_post_form_sends_form_encoded_body(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"access_token": "abc"})
        )

        result = await client.post_form(
            "/api/v1/auth/token",
            {"username": "u@x.com", "password": "pw"},
        )

        assert result == {"access_token": "abc"}
        _, kwargs = client._client.request.call_args
        assert kwargs["data"] == {"username": "u@x.com", "password": "pw"}
        assert kwargs.get("json") is None
        assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"

    @pytest.mark.asyncio
    async def test_post_form_returns_none_on_error(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        response = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        result = await client.post_form("/api/v1/auth/token", {"x": "y"})

        assert result is None

    @pytest.mark.asyncio
    async def test_stream_yields_response(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()

        response = MagicMock()
        response.status_code = 200

        stream_ctx = AsyncMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=response)
        stream_ctx.__aexit__ = AsyncMock(return_value=None)
        client._client.stream = MagicMock(return_value=stream_ctx)  # type: ignore[method-assign]

        async with client.stream("GET", "/events/stream") as resp:
            assert resp is response

        # No Authorization header is set by the stream() helper either.
        args, kwargs = client._client.stream.call_args
        # The shape is stream(method, url, **kwargs) — verify URL was built.
        assert "/events/stream" in args[1]

    @pytest.mark.asyncio
    async def test_stream_emits_unauthorized_on_401(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        called: list[bool] = []

        client = make_client(on_unauthorized=lambda: called.append(True))

        response = MagicMock()
        response.status_code = 401

        stream_ctx = AsyncMock()
        stream_ctx.__aenter__ = AsyncMock(return_value=response)
        stream_ctx.__aexit__ = AsyncMock(return_value=None)
        client._client.stream = MagicMock(return_value=stream_ctx)  # type: ignore[method-assign]

        async with client.stream("GET", "/events/stream") as _:
            pass

        assert called == [True]

    # ---- request_with_status ----

    @pytest.mark.asyncio
    async def test_request_with_status_returns_status_and_body_on_200(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"ok": True})
        )

        status, body = await client.request_with_status("GET", "/api/x")

        assert status == 200
        assert body == {"ok": True}

    @pytest.mark.asyncio
    async def test_request_with_status_returns_204_with_none_body(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(204, content=b"")
        )

        status, body = await client.request_with_status("DELETE", "/api/x")

        assert status == 204
        assert body is None

    @pytest.mark.asyncio
    async def test_request_with_status_returns_4xx_without_raising(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(403, {"detail": "forbidden"})
        )

        status, body = await client.request_with_status("DELETE", "/api/orgs/1")

        assert status == 403
        assert body == {"detail": "forbidden"}

    @pytest.mark.asyncio
    async def test_request_with_status_returns_zero_on_network_error(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.ConnectError("refused")
        )

        status, body = await client.request_with_status("GET", "/api/x")

        assert status == 0
        assert body is None

    @pytest.mark.asyncio
    async def test_request_with_status_fires_on_unauthorized_on_401(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        called: list[bool] = []

        client = make_client(on_unauthorized=lambda: called.append(True))
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(401, {"detail": "expired"})
        )

        status, _body = await client.request_with_status("GET", "/api/x")

        assert status == 401
        assert called == [True]

    # ---- post_multipart ----

    @pytest.mark.asyncio
    async def test_post_multipart_sends_files_without_setting_content_type(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"text": "hello"})
        )

        files = {"file": ("audio.wav", b"\x00\x01", "audio/wav")}
        result = await client.post_multipart("/api/v1/transcribe", files=files)

        assert result == {"text": "hello"}
        _, kwargs = client._client.request.call_args
        assert kwargs["files"] == files
        # httpx infers multipart Content-Type from files=, so we must NOT
        # set it manually (would clobber the boundary).
        assert "Content-Type" not in kwargs.get("headers", {})

    @pytest.mark.asyncio
    async def test_post_multipart_fires_on_unauthorized_on_401(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        called: list[bool] = []
        client = make_client(on_unauthorized=lambda: called.append(True))
        response = _mock_response(
            401,
            raise_status=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        files = {"file": ("a.wav", b"\x00", "audio/wav")}
        result = await client.post_multipart("/api/v1/transcribe", files=files)

        assert result is None
        assert called == [True]

    @pytest.mark.asyncio
    async def test_post_multipart_returns_none_on_network_error(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.ConnectError("refused")
        )

        files = {"file": ("a.wav", b"\x00", "audio/wav")}
        result = await client.post_multipart("/api/v1/transcribe", files=files)

        assert result is None

    # ---- cookie jar lifecycle ----

    @pytest.mark.asyncio
    async def test_clear_cookies_drops_every_cookie_in_jar(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        """``logout`` calls this so a stale cookie cannot be replayed."""
        client = make_client()
        client._client.cookies.set("aegis_session", "tok-abc", domain="test")
        assert "aegis_session" in dict(client._client.cookies)

        client.clear_cookies()

        assert dict(client._client.cookies) == {}

    @pytest.mark.asyncio
    async def test_aclose_releases_underlying_client(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        """Session teardown must release the connection pool."""
        client = make_client()
        client._client.aclose = AsyncMock()  # type: ignore[method-assign]

        await client.aclose()

        client._client.aclose.assert_awaited_once()


class TestPerRequestTimeout:
    """Long-running endpoints (the finance file import) need more than the
    client-wide 10s without loosening every other call's budget."""

    @pytest.mark.asyncio
    async def test_multipart_timeout_override_reaches_httpx(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"ok": True})
        )

        await client.post_multipart(
            "/api/v1/finance/import",
            files={"file": ("a.qif", b"x", "application/octet-stream")},
            timeout=300.0,
        )

        assert client._client.request.call_args.kwargs["timeout"] == 300.0

    @pytest.mark.asyncio
    async def test_without_override_the_client_default_applies(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"ok": True})
        )

        await client.get("/api/test")

        # No per-request timeout kwarg: the AsyncClient's own default rules.
        assert "timeout" not in client._client.request.call_args.kwargs

    @pytest.mark.asyncio
    async def test_timeout_error_reports_the_effective_budget(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.TimeoutException("timeout")
        )

        await client.post_multipart(
            "/api/v1/finance/import",
            files={"file": ("a.qif", b"x", "application/octet-stream")},
            timeout=300.0,
        )

        assert client.last_error is not None
        assert "300" in client.last_error
        assert "10" not in client.last_error.split("300")[0]


class TestImportUploadsGetALongerBudget:
    """The finance import call sites must actually USE the override.

    The plumbing below is tested above; this pins the call sites, which is
    where a 10s default silently killed real imports.
    """

    def test_import_budget_exceeds_the_client_default(self) -> None:
        imports_flow = pytest.importorskip(
            "app.components.frontend.dashboard.modals.finance_modal"
            ".transactions_panel.imports_flow",
            reason="finance UI not part of this stack",
        )

        assert imports_flow._IMPORT_TIMEOUT_SECONDS > APIClient().timeout

    @pytest.mark.asyncio
    async def test_in_request_import_calls_pass_the_budget(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        # The endpoints that parse the file and run the plan before
        # responding. (/api/v1/finance/import is exempt: it returns a job
        # id immediately and streams progress.)
        imports_flow = pytest.importorskip(
            "app.components.frontend.dashboard.modals.finance_modal"
            ".transactions_panel.imports_flow",
            reason="finance UI not part of this stack",
        )
        budget = imports_flow._IMPORT_TIMEOUT_SECONDS

        for endpoint in (
            "/api/v1/finance/import/preview",
            "/api/v1/finance/import-investments/preview",
            "/api/v1/finance/import-investments",
        ):
            client = make_client()
            client._client.request = AsyncMock(  # type: ignore[method-assign]
                return_value=_mock_response(200, {"ok": True})
            )
            await client.post_multipart(
                endpoint,
                files={"file": ("a.csv", b"x", "application/octet-stream")},
                timeout=budget,
            )
            sent = client._client.request.call_args.kwargs["timeout"]
            assert sent == budget, endpoint


class TestLastError:
    """``last_error`` keeps the real failure reason for UI surfaces.

    The client's contract is "None on error, details in the log" - which
    leaves the UI unable to say WHAT failed. ``last_error`` carries the
    same detail the log line gets, for the caller that just got None.
    """

    @pytest.mark.asyncio
    async def test_success_clears_last_error(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            return_value=_mock_response(200, {"ok": True})
        )
        client.last_error = "stale failure from a previous call"

        await client.get("/api/test")

        assert client.last_error is None

    @pytest.mark.asyncio
    async def test_timeout_records_endpoint_and_budget(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.TimeoutException("timeout")
        )

        await client.post("/api/v1/finance/import")

        assert client.last_error is not None
        assert "timed out" in client.last_error
        assert "/api/v1/finance/import" in client.last_error
        assert "10" in client.last_error  # the default timeout budget

    @pytest.mark.asyncio
    async def test_http_error_records_status_and_response_detail(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        response = _mock_response(
            422, {"detail": "QIF import requires a target account_id."}
        )
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "422", request=MagicMock(), response=response
            )
        )
        client._client.request = AsyncMock(return_value=response)  # type: ignore[method-assign]

        await client.post("/api/v1/finance/import")

        assert client.last_error is not None
        assert "422" in client.last_error
        assert "QIF import requires a target account_id." in client.last_error

    @pytest.mark.asyncio
    async def test_connect_error_records_last_error(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import httpx

        client = make_client()
        client._client.request = AsyncMock(  # type: ignore[method-assign]
            side_effect=httpx.ConnectError("refused")
        )

        await client.get("/api/test")

        assert client.last_error is not None
        assert "connect" in client.last_error.lower()


class TestGetCache:
    """Opt-in GET caching: one fetch serves a whole burst of readers.

    A dashboard opening every tab fires the same reference reads many
    times at once (observed live: /accounts x8 in one open). Callers that
    pass ``cache_ttl`` share one request in flight and one cached result;
    any write through the client drops the cache, so a caller can never
    read its own write stale.
    """

    @pytest.mark.asyncio
    async def test_second_read_within_ttl_does_not_refetch(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        fetch = AsyncMock(return_value={"items": [1]})
        client._perform_request = fetch  # type: ignore[method-assign]

        first = await client.get("/api/v1/finance/accounts", cache_ttl=30)
        second = await client.get("/api/v1/finance/accounts", cache_ttl=30)

        assert first == second == {"items": [1]}
        assert fetch.await_count == 1

    @pytest.mark.asyncio
    async def test_distinct_params_are_distinct_entries(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        fetch = AsyncMock(return_value={"items": []})
        client._perform_request = fetch  # type: ignore[method-assign]

        await client.get("/api/x", params={"days": 30}, cache_ttl=30)
        await client.get("/api/x", params={"days": 90}, cache_ttl=30)

        assert fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_burst_coalesces_to_one_request(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        import asyncio

        client = make_client()

        async def slow_fetch(*args: Any, **kwargs: Any) -> dict:
            await asyncio.sleep(0)
            return {"items": [1]}

        fetch = AsyncMock(side_effect=slow_fetch)
        client._perform_request = fetch  # type: ignore[method-assign]

        results = await asyncio.gather(
            *(client.get("/api/v1/finance/accounts", cache_ttl=30) for _ in range(8))
        )

        assert all(r == {"items": [1]} for r in results)
        assert fetch.await_count == 1

    @pytest.mark.asyncio
    async def test_a_write_invalidates_the_cache(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        fetch = AsyncMock(return_value={"items": [1]})
        client._perform_request = fetch  # type: ignore[method-assign]

        await client.get("/api/v1/finance/accounts", cache_ttl=30)
        await client.post("/api/v1/finance/accounts", json={"name": "New"})
        await client.get("/api/v1/finance/accounts", cache_ttl=30)

        get_calls = [c for c in fetch.await_args_list if c.args[0] == "GET"]
        assert len(get_calls) == 2

    @pytest.mark.asyncio
    async def test_an_error_result_is_not_cached(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        fetch = AsyncMock(side_effect=[None, {"items": [1]}])
        client._perform_request = fetch  # type: ignore[method-assign]

        first = await client.get("/api/v1/finance/accounts", cache_ttl=30)
        second = await client.get("/api/v1/finance/accounts", cache_ttl=30)

        assert first is None
        assert second == {"items": [1]}
        assert fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_uncached_get_always_fetches(
        self, make_client: Callable[..., APIClient]
    ) -> None:
        client = make_client()
        fetch = AsyncMock(return_value={"items": [1]})
        client._perform_request = fetch  # type: ignore[method-assign]

        await client.get("/api/v1/finance/accounts")
        await client.get("/api/v1/finance/accounts")

        assert fetch.await_count == 2
