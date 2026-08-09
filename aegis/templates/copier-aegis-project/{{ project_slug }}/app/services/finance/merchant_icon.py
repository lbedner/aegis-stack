"""A payee's brand icon, resolved server-side and inlined as base64.

Why base64 rather than a URL the browser fetches - two independent
reasons, both verified live rather than assumed:

1. The upstream favicon service answers with no
   ``Access-Control-Allow-Origin``. Flutter web loads network images by
   fetch with CORS enforced, so a direct third-party URL is blocked and
   every icon silently degrades to the initial-letter avatar.
2. Pointing at our own origin with a RELATIVE path ("/api/v1/...") does
   not fix it either: Flet resolves a non-absolute ``Image.src`` against
   the app's assets directory, not the HTTP origin - and an absolute one
   would have to guess the browser-facing scheme/host through a tunnel.

Handing the bytes over directly sidesteps all of it. Cost is bounded by
the cache below: 164 distinct domains resolve in ~1.5s concurrently on a
cold start, and nothing after that.

A domain that does not resolve is not an error - it returns None and the
frontend falls back to the initial-letter avatar, the same way an
unmatched merchant degrades everywhere else in this app.
"""

import asyncio
import base64

from app.services.finance.importers.base import normalize_payee

# Below this a "domain" is more likely noise than a brand; above it, the
# string is a bank descriptor rather than a name ("INTEREST CHARGED TO
# PUR PR-11/28/25." -> "interestchargedtopurpr112825.com"), and a fetch
# for it can only ever miss.
_MIN_DOMAIN_LENGTH = 2
_MAX_DOMAIN_LENGTH = 24

UPSTREAM = "https://www.google.com/s2/favicons"

# domain -> base64 png, or None for a domain already known to miss (a
# negative entry matters: without it every render retries the same dead
# lookup). Process-local and bounded - this is a render-path cache, not a
# store, and a favicon carries nothing user-scoped, so there is no leak
# across owners.
_CACHE: dict[str, str | None] = {}
_CACHE_MAX = 2048
_CONCURRENCY = 24
_TIMEOUT_SECONDS = 4.0


def domain_from_website(website_url: str | None) -> str | None:
    """The bare host from a stored payee website - the AUTHORITATIVE source
    when a payee has one, because guessing cannot reach it.

    The guess below only ever tries ``<name>.com``, which is wrong in two
    ways a user can trivially fix by typing the real address: it misses
    every other TLD ("aegis-stack.io"), and it strips the punctuation that
    was part of the name ("Aegis Stack" -> "aegisstack", never
    "aegis-stack"). Worse, a plausible-looking ``.com`` may belong to
    somebody else entirely - "aegis-stack.com" resolves to a real, unrelated
    site - so a confident guess can render a stranger's logo on your bill.
    An explicit domain removes all of that.
    """
    raw = (website_url or "").strip()
    if not raw:
        return None
    host = raw.split("//", 1)[-1]  # drop any scheme
    host = host.split("/", 1)[0]  # drop any path
    host = host.split("?", 1)[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    # A bare host has a dot and no spaces; anything else was not a domain.
    return host if ("." in host and " " not in host and len(host) > 3) else None


# A fund's FULL name never guesses to a usable domain the way
# ``merchant_icon_domain`` guesses a payee's - "Vanguard Total Intl Stk Idx
# I" squashed whole is "vanguardtotalintlstkidxi.com", nothing. But the
# ISSUER does, and it's reliably the name's first word ("Vanguard", "Schwab",
# "Fidelity", "iShares", ...), the same generic one-word-guess idea, just
# scoped to where a fund name actually keeps its brand instead of squashing
# the whole descriptive string. Explicit overrides exist only for the
# issuers whose real domain the first word gets wrong (a multi-word name, or
# a sub-brand trading under its parent's site).
_FUND_FAMILY_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("spdr", "ssga.com"),  # SPDR funds are issued by State Street
    ("state street", "ssga.com"),
    ("t. rowe price", "troweprice.com"),
    ("t rowe price", "troweprice.com"),
    ("american funds", "americanfunds.com"),
    ("dodge & cox", "dodgeandcox.com"),
)


def fund_family_domain(security_name: str | None) -> str | None:
    """The issuing fund family's domain - checked overrides first (the
    handful of issuers a first-word guess gets wrong), otherwise the
    generic guess: ``<first word>.com``. AUTHORITATIVE either way, the same
    role ``domain_from_website`` plays for a payee - a fund's descriptive
    suffix ("Total Intl Stk Idx I") is never worth guessing past the brand.
    """
    lowered = (security_name or "").lower()
    for needle, domain in _FUND_FAMILY_OVERRIDES:
        if needle in lowered:
            return domain
    first_word = lowered.split()[0].strip(".,&") if lowered.split() else ""
    if len(first_word) < _MIN_DOMAIN_LENGTH:
        return None
    return f"{first_word}.com"


def merchant_icon_domain(payee_name: str | None) -> str | None:
    """The domain guessed from ``payee_name``, or None when there is
    nothing plausible to guess from."""
    normalized = normalize_payee(payee_name)
    domain = normalized.replace(" ", "").lower()
    if not (_MIN_DOMAIN_LENGTH <= len(domain) <= _MAX_DOMAIN_LENGTH):
        return None
    return f"{domain}.com"


async def icons_for_names(
    names: list[str | None],
    domains_by_name: dict[str, str] | None = None,
) -> dict[str, str]:
    """``{payee name: base64 png}`` for whichever names resolve.

    Batched and concurrent on purpose: a list endpoint needs icons for a
    whole page at once, and doing that one await at a time is the
    difference between ~1.5s and a minute. Names that share a domain
    (and anything already cached) cost nothing extra.
    """
    overrides = domains_by_name or {}
    wanted: dict[str, str] = {}  # name -> domain
    for name in names:
        if not name or name in wanted:
            continue
        # An explicit domain always wins over the guess.
        domain = overrides.get(name) or merchant_icon_domain(name)
        if domain is not None:
            wanted[name] = domain

    missing = sorted({d for d in wanted.values() if d not in _CACHE})
    if missing:
        await _fetch_many(missing)
    resolved: dict[str, str] = {}
    for name, domain in wanted.items():
        cached = _CACHE.get(domain)
        if cached is not None:
            resolved[name] = cached
    return resolved


async def _fetch_many(domains: list[str]) -> None:
    import httpx

    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def one(client, domain: str) -> None:
        async with semaphore:
            try:
                # follow_redirects: the service answers 301 to its real
                # asset host and httpx (unlike urllib) does not follow by
                # default - without this every icon misses on a redirect
                # it should have chased.
                response = await client.get(
                    UPSTREAM, params={"sz": 64, "domain": domain}
                )
                payload = response.content if response.status_code == 200 else b""
            except Exception:
                # Includes having no network at all. An icon is never
                # worth failing the page it decorates.
                payload = b""
        if len(_CACHE) < _CACHE_MAX:
            _CACHE[domain] = base64.b64encode(payload).decode() if payload else None

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            await asyncio.gather(*(one(client, d) for d in domains))
    except Exception:
        return
