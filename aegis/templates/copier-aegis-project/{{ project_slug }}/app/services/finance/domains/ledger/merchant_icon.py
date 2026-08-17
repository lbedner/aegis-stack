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

Handing the bytes over directly sidesteps all of it.

The request path NEVER fetches. Resolution reads memory, then the
``finance_icon`` table; domains neither knows are handed to a background
task that fetches upstream and persists what it finds, so the first page
after a genuine miss renders the initial-letter fallback and the next one
has the icon. Before this, a process restart emptied the in-memory cache
and the next render paid ~130 sequential-ish upstream round trips inside
the request (observed: a 946ms overview that spent ~99% on favicons).

A domain that does not resolve is not an error - it is stored as a
NEGATIVE row (NULL bytes) so it is not retried until the row ages out,
and the frontend falls back to the initial-letter avatar, the same way an
unmatched merchant degrades everywhere else in this app.
"""

import asyncio
import base64
from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import queries
from app.services.finance.models import FinanceIcon
from app.services.finance.utils import normalize_payee, utcnow

# Below this a "domain" is more likely noise than a brand; above it, the
# string is a bank descriptor rather than a name ("INTEREST CHARGED TO
# PUR PR-11/28/25." -> "interestchargedtopurpr112825.com"), and a fetch
# for it can only ever miss.
_MIN_DOMAIN_LENGTH = 2
_MAX_DOMAIN_LENGTH = 24

UPSTREAM = "https://www.google.com/s2/favicons"

# domain -> base64 png, or None for a domain already known to miss. A
# read-through layer over finance_icon rows - it only ever mirrors what
# the table says (or what a fill just stored), so bounded process-local
# state, and nothing user-scoped.
_CACHE: dict[str, str | None] = {}
_CACHE_MAX = 4096
_CONCURRENCY = 24
_TIMEOUT_SECONDS = 4.0

# A stored miss is retried this much later. Brands do gain favicons (a
# payee's website gets set, a new brand launches), just not per-render.
_NEGATIVE_RETRY = timedelta(days=7)

# Domains a background fill is already fetching - a burst of requests over
# the same cold page must not schedule the same upstream fetch N times.
_IN_FLIGHT: set[str] = set()


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
    db: AsyncSession,
    names: list[str | None],
    domains_by_name: dict[str, str] | None = None,
) -> dict[str, str]:
    """``{payee name: base64 png}`` for whichever names resolve NOW.

    Memory first, then stored ``finance_icon`` rows. Domains neither
    layer knows (or whose negative entry has aged out) are scheduled for
    a background fill and simply absent from this response - the caller's
    page renders its fallback once and finds the icon on the next load.
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

    unknown = sorted({d for d in wanted.values() if d not in _CACHE})
    if unknown:
        stored = await queries.icons_by_domains(db, unknown)
        now = utcnow()
        to_fetch: list[str] = []
        for domain in unknown:
            row = stored.get(domain)
            if row is None:
                to_fetch.append(domain)
            elif row.icon_b64 is None and now - row.fetched_at > _NEGATIVE_RETRY:
                to_fetch.append(domain)
            else:
                _remember(domain, row.icon_b64)
        if to_fetch:
            _schedule_fill(to_fetch)

    resolved: dict[str, str] = {}
    for name, domain in wanted.items():
        cached = _CACHE.get(domain)
        if cached is not None:
            resolved[name] = cached
    return resolved


def _remember(domain: str, icon_b64: str | None) -> None:
    if len(_CACHE) < _CACHE_MAX:
        _CACHE[domain] = icon_b64


def _schedule_fill(domains: list[str]) -> None:
    """Kick off a fire-and-forget fill for ``domains``, skipping any a
    running fill already covers. Never awaited by a request."""
    fresh = [d for d in domains if d not in _IN_FLIGHT]
    if not fresh:
        return
    _IN_FLIGHT.update(fresh)
    task = asyncio.create_task(_fill_icons(fresh))
    # A render-path decoration is never worth an "exception was never
    # retrieved" warning; failures were already logged/stored as misses.
    task.add_done_callback(lambda t: t.exception())


async def _fill_icons(domains: list[str]) -> None:
    """Fetch ``domains`` upstream and persist every answer - bytes or a
    negative row - in its own session (the requesting session is gone)."""
    from app.core.db import get_async_session

    try:
        fetched = await _fetch_domains(domains)
        async with get_async_session() as db:
            existing = await queries.icons_by_domains(db, fetched.keys())
            now = utcnow()
            for domain, icon_b64 in fetched.items():
                row = existing.get(domain)
                if row is None:
                    db.add(
                        FinanceIcon(domain=domain, icon_b64=icon_b64, fetched_at=now)
                    )
                else:
                    row.icon_b64 = icon_b64
                    row.fetched_at = now
                    db.add(row)
                _remember(domain, icon_b64)
    finally:
        _IN_FLIGHT.difference_update(domains)


async def _fetch_domains(domains: list[str]) -> dict[str, str | None]:
    """``{domain: base64 png or None}`` from the upstream favicon service,
    concurrently. None means the domain answered with no usable icon -
    an answer worth storing, not an error."""
    import httpx

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    results: dict[str, str | None] = {}

    async def one(client: "httpx.AsyncClient", domain: str) -> None:
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
        results[domain] = base64.b64encode(payload).decode() if payload else None

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            await asyncio.gather(*(one(client, d) for d in domains))
    except Exception:
        # No network at all: report every domain as a miss so the negative
        # rows still bound retries.
        return {domain: results.get(domain) for domain in domains}
    return results
