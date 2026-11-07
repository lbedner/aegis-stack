"""A fetch of a host somebody else chose, refused off the public internet (#485).

The assistant picks the host ``look_up_contact`` reads, and an injected
document can pick it for her. So the name is resolved here, every address
it resolves to has to be public, and the connection goes to the address
that was checked: a second lookup at connect time could rebind the name
onto an internal service. DNS and the web are faked (``tests/_fake_dns``).
"""

from __future__ import annotations

import httpx
import pytest

from app.core import safe_fetch
from tests._fake_dns import answering, resolving_to


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.10",
        "169.254.169.254",  # the cloud metadata service
        "100.100.100.200",  # shared address space, another metadata host
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fd00:ec2::254",  # the cloud metadata service over IPv6
        "::ffff:127.0.0.1",  # IPv4 written as IPv6
        "64:ff9b::a00:1",  # 10.0.0.1 through a NAT64 gateway
    ],
)
async def test_a_host_resolving_inward_is_refused_before_connecting(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    resolving_to(monkeypatch, [address])
    sent = answering(monkeypatch, httpx.Response(200, text="ok"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(safe_fetch.BlockedAddressError):
            async with safe_fetch.guarded_get(
                client, "https://innocent.example/contact"
            ):
                pass

    assert sent == []


async def test_one_inward_address_among_public_ones_refuses_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A name with a public and a private answer is not a public name."""
    resolving_to(monkeypatch, ["93.184.216.34", "10.0.0.5"])
    sent = answering(monkeypatch, httpx.Response(200, text="ok"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(safe_fetch.BlockedAddressError):
            async with safe_fetch.guarded_get(client, "https://innocent.example/"):
                pass

    assert sent == []


async def test_a_public_host_is_fetched_at_the_address_that_was_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connected by IP, so DNS is not asked twice; the Host header and the
    TLS name stay the host's, so virtual hosting and certificate checks
    work as if the name had been dialled."""
    asked = resolving_to(monkeypatch, ["93.184.216.34"])
    sent = answering(monkeypatch, httpx.Response(200, text="ok"))

    async with httpx.AsyncClient() as client:
        async with safe_fetch.guarded_get(
            client, "https://innocent.example/contact?x=1"
        ) as response:
            assert await safe_fetch.read_capped(response) == "ok"

    assert asked == ["innocent.example"]
    (request,) = sent
    assert request.url.host == "93.184.216.34"
    assert request.url.path == "/contact"
    assert request.url.query == b"x=1"
    assert request.headers["host"] == "innocent.example"
    assert request.extensions["sni_hostname"] == "innocent.example"


async def test_a_public_ipv6_host_keeps_its_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolving_to(monkeypatch, ["2606:4700::1111"])
    sent = answering(monkeypatch, httpx.Response(200, text="ok"))

    async with httpx.AsyncClient() as client:
        async with safe_fetch.guarded_get(client, "https://innocent.example:8443/"):
            pass

    (request,) = sent
    assert request.url.host == "2606:4700::1111"
    assert request.url.port == 8443
    assert request.headers["host"] == "innocent.example:8443"


def test_public_addresses_are_public() -> None:
    assert safe_fetch.is_public("93.184.216.34")
    assert safe_fetch.is_public("2606:4700::1111")
    assert safe_fetch.is_public("::ffff:93.184.216.34")


async def test_a_client_that_follows_redirects_is_not_followed_past_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``guarded_get`` never follows a redirect, whatever the client says:
    the next hop is the caller's to send back through the check."""
    resolving_to(monkeypatch, ["93.184.216.34"])
    sent = answering(
        monkeypatch,
        httpx.Response(302, headers={"location": "http://10.0.0.5/"}),
        httpx.Response(200, text="inside"),
    )

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async with safe_fetch.guarded_get(client, "https://innocent.example/") as r:
            assert r.status_code == 302

    assert len(sent) == 1


class TestGuardedFollow:
    async def test_each_hop_is_resolved_and_checked_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked = resolving_to(monkeypatch, ["93.184.216.34"], ["10.0.0.5"])
        sent = answering(
            monkeypatch,
            httpx.Response(302, headers={"location": "https://inside.example/x"}),
        )

        async with httpx.AsyncClient() as client:
            with pytest.raises(safe_fetch.BlockedAddressError):
                async with safe_fetch.guarded_follow(
                    client, "https://innocent.example/", redirects=3
                ):
                    pass

        assert asked == ["innocent.example", "inside.example"]
        assert len(sent) == 1

    async def test_a_public_redirect_is_followed_to_its_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"])
        sent = answering(
            monkeypatch,
            httpx.Response(301, headers={"location": "/moved"}),
            httpx.Response(200, text="here"),
        )

        async with httpx.AsyncClient() as client:
            async with safe_fetch.guarded_follow(
                client, "https://innocent.example/", redirects=1
            ) as response:
                assert await safe_fetch.read_capped(response) == "here"

        assert [r.url.path for r in sent] == ["/", "/moved"]
        assert sent[1].headers["host"] == "innocent.example"

    async def test_past_the_budget_the_redirect_is_the_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"])
        sent = answering(
            monkeypatch, httpx.Response(302, headers={"location": "/again"})
        )

        async with httpx.AsyncClient() as client:
            async with safe_fetch.guarded_follow(
                client, "https://innocent.example/", redirects=2
            ) as response:
                assert response.status_code == 302

        assert len(sent) == 3

    async def test_a_hop_off_the_named_host_is_not_taken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"])
        sent = answering(
            monkeypatch,
            httpx.Response(301, headers={"location": "//elsewhere.example/"}),
        )

        async with httpx.AsyncClient() as client:
            async with safe_fetch.guarded_follow(
                client,
                "https://innocent.example/",
                redirects=1,
                same_host="innocent.example",
            ) as response:
                assert response.status_code == 301

        assert len(sent) == 1


class TestFetchImage:
    async def test_an_image_comes_back_as_bytes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"])
        answering(monkeypatch, httpx.Response(200, content=b"\x89PNG"))

        async with httpx.AsyncClient() as client:
            image = await safe_fetch.fetch_image(client, "https://cdn.example/a.png")

        assert image == b"\x89PNG"

    async def test_an_image_past_the_cap_is_a_miss_not_a_cut_image(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"])
        answering(
            monkeypatch,
            httpx.Response(200, content=b"x" * (safe_fetch.MAX_IMAGE_BYTES + 1)),
        )

        async with httpx.AsyncClient() as client:
            assert await safe_fetch.fetch_image(client, "https://cdn.example/") is None

    async def test_an_error_status_is_a_miss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolving_to(monkeypatch, ["93.184.216.34"])
        answering(monkeypatch, httpx.Response(404, content=b"not here"))

        async with httpx.AsyncClient() as client:
            assert await safe_fetch.fetch_image(client, "https://cdn.example/") is None
