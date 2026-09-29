"""A brand's logo by its domain, from the upstream favicon service: the
one fetcher finance (payee marks) and the AI catalog (provider marks)
share. Never fails a caller: a miss, an error or no network all come
back as None for that domain."""

import base64

import httpx

from app.core.brand_icons import UPSTREAM, domain_of, fetch_icons


def test_domain_of_takes_the_bare_host() -> None:
    assert domain_of("https://www.anthropic.com/news?x=1") == "anthropic.com"
    assert domain_of("platform.openai.com/api-keys") == "platform.openai.com"
    assert domain_of("not a url") is None
    assert domain_of(None) is None


async def test_fetch_icons_returns_base64_or_none_per_domain() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(UPSTREAM)
        if request.url.params["domain"] == "anthropic.com":
            return httpx.Response(200, content=b"PNG")
        return httpx.Response(404)

    icons = await fetch_icons(
        ["anthropic.com", "nowhere.invalid"], transport=httpx.MockTransport(answer)
    )
    assert icons == {
        "anthropic.com": base64.b64encode(b"PNG").decode(),
        "nowhere.invalid": None,
    }


async def test_no_network_is_a_miss_not_an_error() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    icons = await fetch_icons(["anthropic.com"], transport=httpx.MockTransport(down))
    assert icons == {"anthropic.com": None}
