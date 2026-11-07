"""Web search, for the organization nobody has heard of (#173).

Searching is a capability, not a fact: an agent's ``web_search`` tool, a
lookup that confirms an organization's website, anything that needs a
name found. So it lives here, and callers decide what a hit means. A
result is only ever a candidate: a caller that verifies fetches the page
and checks it says what the hit claimed.

Off unless ``BRAVE_SEARCH_API_KEY`` is set. That is the whole setting:
absent means off, not an error or a warning on every call.

The cache and the daily budget are the privacy mechanism, not only a
cost control. One query is nothing; a year of them reads as a profile
of the user. A repeated lookup emits no new query, and a day can only
emit so many.

Queries name the THING being looked for, never the user: no person, no
case number, no document text.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from app.core.cache import get_cache
from app.core.config import settings
from app.core.log import logger

PROVIDER = "brave"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT_SECONDS = 6.0
# A lookup is repeated for as long as the organization exists; a
# quarter is long enough that a year of them emits a handful of queries.
_CACHE_TTL = 90 * 24 * 3600
_DAY_TTL = 26 * 3600
# Queries a day may emit: the bound on how much pattern ever leaves.
# 25 a day keeps any month inside Brave's $5 free credit (~1,000).
DAILY_BUDGET = 25

# Pages that carry an organization's name more prominently than its own
# site does. confirm() checks that the name is on the page, and on these
# it always is, so they are dropped before verification rather than
# accepted as the organization's website.
DIRECTORIES = frozenset(
    {
        "yelp.com",
        "facebook.com",
        "linkedin.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "youtube.com",
        "wikipedia.org",
        "mapquest.com",
        "yellowpages.com",
        "bbb.org",
        "indeed.com",
        "glassdoor.com",
        "healthgrades.com",
        "medicare.gov",
        "npiregistry.cms.hhs.gov",
        "google.com",
        "bing.com",
        "zoominfo.com",
        "manta.com",
        "caring.com",
        "usnews.com",
        # The state's facility profiles: name and address, never theirs.
        "profiles.health.ny.gov",
    }
)


class SearchHit(BaseModel):
    """One result, whichever provider found it."""

    title: str = ""
    url: str
    snippet: str = ""


class _BraveResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    url: str | None = None
    description: str = ""


class _BraveWeb(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_BraveResult] = []


class _BraveResponse(BaseModel):
    """Brave's answer, validated at the door: only what is read is named,
    everything else is ignored, and a missing section is no results."""

    model_config = ConfigDict(extra="ignore")

    web: _BraveWeb | None = None


def parse_brave(body: dict[str, Any]) -> list[SearchHit]:
    """Brave's JSON as hits; a result without a URL is not a hit."""
    web = _BraveResponse.model_validate(body).web
    return [
        SearchHit(title=r.title, url=r.url, snippet=r.description)
        for r in (web.results if web else [])
        if r.url
    ]


def _spoken(query: str) -> str:
    return " ".join(query.split())


def _normalized(query: str) -> str:
    """The cache's key: the same lookup however it was spaced or cased."""
    return _spoken(query).casefold()


async def search(query: str, *, limit: int = 5) -> list[SearchHit]:
    """Up to ``limit`` hits as ``{title, url, snippet}``, or [] when search
    is off, the day's budget is spent, or the provider fails."""
    key = settings.BRAVE_SEARCH_API_KEY
    wanted = _normalized(query)
    if not key or not wanted:
        return []
    cache = get_cache()
    cached = await cache.get(f"search:q:{PROVIDER}:{wanted}")
    if cached is not None:
        # Stored as plain dicts, so the cache holds no class a later
        # version of this module might not be able to unpickle.
        return [SearchHit.model_validate(hit) for hit in cached][:limit]
    spent = await _spent_today()
    if spent >= DAILY_BUDGET:
        logger.info("search.budget_spent", provider=PROVIDER, spent=spent)
        return []
    await cache.set(_day_key(), spent + 1, ttl=_DAY_TTL)
    try:
        hits = await _brave(_spoken(query), key=key, limit=limit)
    except Exception as exc:  # a lookup is a convenience, never an outage
        logger.warning("search.failed", provider=PROVIDER, error=str(exc))
        return []
    await cache.set(
        f"search:q:{PROVIDER}:{wanted}",
        [hit.model_dump() for hit in hits],
        ttl=_CACHE_TTL,
    )
    return hits[:limit]


def candidates(hits: list[SearchHit]) -> list[str]:
    """What a lookup that verifies should try: each hit's host and path,
    ``www.`` and any query dropped, in rank order, directories left out.

    The PAGE that matched, not only its host. Maple's page is
    examplehealthcare.com/maple/ - the parent company's page for the
    facility - and cut to the host, confirm() checked the parent's home
    page, which is not theirs (2026-09-23).
    """
    seen: list[str] = []
    for hit in hits:
        parts = urlsplit(hit.url)
        host = (parts.hostname or "").removeprefix("www.")
        if not host or any(host == d or host.endswith(f".{d}") for d in DIRECTORIES):
            continue
        candidate = f"{host}{parts.path}"
        if candidate not in seen:
            seen.append(candidate)
    return seen


async def status() -> dict[str, Any]:
    """What the health report shows: the provider, whether a key is set,
    and today's queries against the budget. Never the key itself."""
    return {
        "provider": PROVIDER,
        "enabled": bool(settings.BRAVE_SEARCH_API_KEY),
        "queries_today": await _spent_today(),
        "daily_budget": DAILY_BUDGET,
    }


def _day_key() -> str:
    from app.core.time import today

    return f"search:day:{PROVIDER}:{today().isoformat()}"


async def _spent_today() -> int:
    return int(await get_cache().get(_day_key()) or 0)


async def _brave(query: str, *, key: str, limit: int) -> list[SearchHit]:
    """One Brave web search. No cookies, no profile, one query."""
    import httpx

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(
            _BRAVE_URL,
            params={"q": query, "count": limit},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
        response.raise_for_status()
    return parse_brave(response.json())
