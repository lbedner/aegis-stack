"""One GET of a URL somebody else chose, kept on the public internet (#485).

The assistant picks the hosts ``look_up_contact`` reads, and an injected
document can pick them for her. Left alone, httpx would happily read an
internal HTTPS service or the cloud metadata address and hand the text
back to the model.

So the host is resolved HERE, every address it resolves to must be
public, and the request is sent to the checked IP rather than the name:
a second lookup at connect time is exactly where a rebinding name swaps
in 127.0.0.1. The Host header and the TLS server name (``sni_hostname``,
which httpcore also uses to verify the certificate) stay the original
host's, so virtual hosting and certificate checks behave as if the name
had been dialled.

``guarded_get`` never follows a redirect, whatever the client says.
``guarded_follow`` is the one place hops are taken: each next URL goes
back through ``guarded_get``, so every target is resolved and checked
again. The body is the caller's to judge, and is never read past a cap:
``MAX_BODY_BYTES`` for text, ``MAX_IMAGE_BYTES`` for ``fetch_image``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import ipaddress
import socket

import httpx

# The most of a body any caller reads. A contact page is tens of KB; a
# host the model chose can answer with an endless one.
MAX_BODY_BYTES = 2 * 1024 * 1024
# The most of an image kept: a logo or an avatar is tens of KB (#493).
MAX_IMAGE_BYTES = 200_000

REDIRECTS = (301, 302, 303, 307, 308)

# NAT64's well-known prefix carries an IPv4 address in its last 32 bits,
# and a cloud NAT64 gateway will route it to a private one.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class BlockedAddressError(Exception):
    """The host resolves somewhere this app must not fetch from."""


def is_public(address: str) -> bool:
    """Whether an address is on the public internet.

    IPv4 written as IPv6 (``::ffff:127.0.0.1``, NAT64) is judged as the
    IPv4 it carries. ``is_global`` rules out private, loopback,
    link-local, unspecified and shared address space (100.64.0.0/10,
    where one cloud keeps its metadata service); multicast and reserved
    are not covered by it.
    """
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not (ip.is_multicast or ip.is_reserved)


async def _resolve(host: str, port: int) -> list[str]:
    """Every address a host resolves to (scope ids dropped)."""
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(str(info[4][0]).split("%")[0] for info in infos))


@asynccontextmanager
async def guarded_get(
    client: httpx.AsyncClient, url: str
) -> AsyncIterator[httpx.Response]:
    """GET ``url`` at a checked public address, body unread, or raise.

    Raises ``BlockedAddressError`` when any address the host resolves to
    is not public; nothing is sent. Never follows a redirect itself. The
    body is streamed: check status and content-type, then ``read_capped``
    it. The response is closed on the way out either way.
    """
    target = httpx.URL(url)
    if target.scheme not in ("http", "https") or not target.host:
        raise BlockedAddressError(f"not a web URL: {url}")
    port = target.port or (443 if target.scheme == "https" else 80)
    # The client's connect timeout covers the lookup too, as it did when
    # httpx resolved the name itself.
    async with asyncio.timeout(client.timeout.connect):
        addresses = await _resolve(target.host, port)
    if not addresses or not all(is_public(address) for address in addresses):
        raise BlockedAddressError(f"{target.host} resolves to {addresses}")
    extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
    request = client.build_request(
        "GET",
        target.copy_with(host=addresses[0]),
        headers={"Host": target.netloc.decode("ascii")},
        extensions=extensions,
    )
    # A client built to follow redirects would chase one here, unchecked.
    response = await client.send(request, stream=True, follow_redirects=False)
    try:
        yield response
    finally:
        await response.aclose()


@asynccontextmanager
async def guarded_follow(
    client: httpx.AsyncClient,
    url: str,
    *,
    redirects: int,
    same_host: str | None = None,
) -> AsyncIterator[httpx.Response]:
    """``guarded_get``, taking up to ``redirects`` hops, each one resolved
    and checked again. A redirect not taken is the answer: one past the
    budget, one with no location, and with ``same_host`` one onto any
    other host. Raises ``BlockedAddressError`` as ``guarded_get`` does.
    """
    for hop in range(redirects + 1):
        async with guarded_get(client, url) as response:
            location = response.headers.get("location")
            if hop < redirects and response.status_code in REDIRECTS and location:
                # Joined onto the URL asked for: the response's own URL
                # carries the IP it was dialled at, not the host.
                target = httpx.URL(url).join(location)
                if same_host is None or target.host == same_host:
                    url = str(target)
                    continue
            yield response
            return


async def fetch_image(
    client: httpx.AsyncClient, url: str, *, redirects: int = 3
) -> bytes | None:
    """The image at a URL someone else chose: a 200's body, or None for
    any other answer and for a body past ``MAX_IMAGE_BYTES`` (a cut image
    is a broken one). Raises ``BlockedAddressError`` as ``guarded_get``
    does."""
    async with guarded_follow(client, url, redirects=redirects) as response:
        if response.status_code != 200:
            return None
        body = await _read_bytes(response, MAX_IMAGE_BYTES + 1)
    return body if len(body) <= MAX_IMAGE_BYTES else None


async def _read_bytes(response: httpx.Response, limit: int) -> bytes:
    """A streamed body, read no further than ``limit`` bytes. Counted
    after content-decoding, so a small gzip bomb is cut off too."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) >= limit:
            break
    return bytes(body[:limit])


async def read_capped(response: httpx.Response, limit: int = MAX_BODY_BYTES) -> str:
    """The text of a streamed body, read no further than ``limit`` bytes."""
    return (await _read_bytes(response, limit)).decode(
        response.charset_encoding or "utf-8", errors="replace"
    )
