"""``GraphQLClient``: the wire shape, the error mapping, and the seam.

Everything here runs against ``httpx.MockTransport`` - no network. That
transport injection is the point of the class: a consumer test hands in a
fake and never monkeypatches ``httpx``.
"""

from __future__ import annotations

import json

import httpx
import pytest
from app.core.graphql import GraphQLClient, GraphQLError, GraphQLHTTPError


def _transport(handler):
    return httpx.MockTransport(handler)


async def test_posts_query_and_variables_and_returns_data() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"viewer": {"login": "octocat"}}})

    async with GraphQLClient(
        "https://example.test/graphql",
        headers={"Authorization": "Bearer t"},
        transport=_transport(handler),
    ) as client:
        data = await client.query("query { viewer { login } }", {"n": 1})

    assert data == {"viewer": {"login": "octocat"}}
    assert seen["method"] == "POST"
    assert seen["url"] == "https://example.test/graphql"
    assert seen["body"] == {
        "query": "query { viewer { login } }",
        "variables": {"n": 1},
    }
    assert seen["auth"] == "Bearer t"


async def test_omitted_variables_send_an_empty_object() -> None:
    """GraphQL servers accept a missing ``variables`` key, but some reject
    ``null``; always send an object so the client never has to think."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {}})

    async with GraphQLClient("https://x/graphql", transport=_transport(handler)) as c:
        await c.query("{ ok }")

    assert seen["body"]["variables"] == {}


async def test_errors_array_raises_even_on_200() -> None:
    """GraphQL reports resolver failures with a 200 and an ``errors`` array.
    Without this every caller would have to remember to check."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": None,
                "errors": [{"message": "Field 'nope' doesn't exist", "path": ["nope"]}],
            },
        )

    async with GraphQLClient("https://x/graphql", transport=_transport(handler)) as c:
        with pytest.raises(GraphQLError) as exc:
            await c.query("{ nope }")

    assert "nope" in str(exc.value)
    assert exc.value.errors[0]["path"] == ["nope"]


async def test_non_2xx_raises_http_error_with_status_and_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    async with GraphQLClient("https://x/graphql", transport=_transport(handler)) as c:
        with pytest.raises(GraphQLHTTPError) as exc:
            await c.query("{ ok }")

    assert exc.value.status == 502
    assert "bad gateway" in exc.value.body
    # Callers catch the client's own type, never httpx's.
    assert not isinstance(exc.value, httpx.HTTPError)


async def test_transport_failure_is_wrapped_not_leaked() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with GraphQLClient("https://x/graphql", transport=_transport(handler)) as c:
        with pytest.raises(GraphQLHTTPError) as exc:
            await c.query("{ ok }")

    assert exc.value.status is None
    assert "refused" in exc.value.body


async def test_reuses_one_connection_pool_across_calls() -> None:
    """One ``AsyncClient`` per instance, not per call - the whole reason
    to hold a client object rather than a function."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    client = GraphQLClient("https://x/graphql", transport=_transport(handler))
    async with client:
        first = client._http
        await client.query("{ a }")
        await client.query("{ b }")
        assert client._http is first
