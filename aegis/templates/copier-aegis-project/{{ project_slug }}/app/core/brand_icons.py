"""A brand's logo by its domain: the one fetcher every mark in the app
comes from (a payee's in finance, a provider's in the AI catalog).

Callers own where the answer is kept and when to ask; this only answers
"what does the upstream favicon service have for these domains", and it
never fails a caller. A domain with no usable icon, an upstream error and
having no network at all each come back as None for that domain: an
answer worth storing (so a miss is not retried every time), not an
exception. It never runs inside a request; callers fetch in the
background or at sync time and store the bytes.
"""

import asyncio
import base64
from collections.abc import Iterable
from urllib.parse import urlencode

import httpx

UPSTREAM = "https://www.google.com/s2/favicons"
ICON_SIZE = 64
CONCURRENCY = 24
TIMEOUT_SECONDS = 4.0


def domain_of(url: str | None) -> str | None:
    """The bare host of a URL or a typed address: scheme, path, query and a
    leading ``www.`` dropped. None when it was never a domain."""
    raw = (url or "").strip()
    if not raw:
        return None
    host = raw.split("//", 1)[-1]  # drop any scheme
    host = host.split("/", 1)[0]  # drop any path
    host = host.split("?", 1)[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    # A bare host has a dot and no spaces; anything else was not a domain.
    return host if ("." in host and " " not in host and len(host) > 3) else None


def favicon_url(domain: str) -> str:
    """The upstream's URL for ``domain``'s icon, for a page to load itself
    (a short, fixed list of marks, like the hosting providers'), where a
    long or user-made list is fetched and stored with ``fetch_icons``."""
    return f"{UPSTREAM}?{urlencode(_params(domain))}"


def _params(domain: str) -> dict[str, str | int]:
    return {"sz": ICON_SIZE, "domain": domain}


async def fetch_icons(
    domains: Iterable[str], *, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, str | None]:
    """``{domain: base64 png or None}``, fetched concurrently. ``transport``
    is for tests (an ``httpx.MockTransport``)."""
    wanted = list(dict.fromkeys(domains))
    semaphore = asyncio.Semaphore(CONCURRENCY)
    results: dict[str, str | None] = dict.fromkeys(wanted)

    async def one(client: httpx.AsyncClient, domain: str) -> None:
        async with semaphore:
            try:
                response = await client.get(UPSTREAM, params=_params(domain))
            except httpx.HTTPError:
                return  # no network, a timeout: a miss for this domain
        if response.status_code == 200 and response.content:
            results[domain] = base64.b64encode(response.content).decode()

    # follow_redirects: the service answers 301 to its real asset host, and
    # httpx does not follow by default; without it every icon would miss.
    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=True, transport=transport
    ) as client:
        await asyncio.gather(*(one(client, d) for d in wanted))
    return results
