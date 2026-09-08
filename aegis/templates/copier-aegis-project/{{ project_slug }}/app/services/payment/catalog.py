"""
Catalog cache for the payment service.

Populates the Actions-tab "Price" dropdown from the provider's live catalog
(Stripe Product/Price API). Cached in-process so opening the tab doesn't
re-hit Stripe on every poll — same TTL pattern as the health cache but
independent: different endpoint, different consumer, different cache.
"""

import logging
import time

from .service import PaymentService
from .providers.base import CatalogEntry

logger = logging.getLogger(__name__)

# Same TTL as provider health — one Stripe call per minute per worker keeps
# the dropdown usable without hammering the API. Catalog changes are rare
# and the webhook-driven invalidation hook covers the "I just added a price
# and want to see it now" case.
_CACHE_TTL_SECONDS = 60.0
_cached_catalog: tuple[list[CatalogEntry], float] | None = None


async def get_catalog(service: PaymentService) -> list[CatalogEntry]:
    """Return the active provider catalog, from cache or live API.

    First call per worker (and first call after cache expiry) fetches from
    the provider and populates the cache. Subsequent calls within the TTL
    return the cached list without a round-trip.
    """
    global _cached_catalog

    now = time.monotonic()
    if _cached_catalog is not None:
        entries, cached_at = _cached_catalog
        if now - cached_at < _CACHE_TTL_SECONDS:
            return entries

    entries = await service.provider.list_catalog()
    _cached_catalog = (entries, now)
    return entries


def invalidate_catalog_cache() -> None:
    """Drop the cached catalog so the next call re-fetches from the provider.

    Call after any ``product.*`` or ``price.*`` webhook if you wire those
    up, or after a manual catalog change you want reflected immediately.
    """
    global _cached_catalog
    _cached_catalog = None
