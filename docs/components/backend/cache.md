# Cache

A small, async, time-limited cache for values that are expensive to compute and fine to be a little stale: aggregated metrics, catalog lookups, rendered summaries. It lives in `app/core/cache.py` and is present in every project.

```python
from app.core.cache import cache

await cache.set("insights:summary:7", summary, ttl=300)  # seconds; default 300
summary = await cache.get("insights:summary:7")        # None if missing or expired
await cache.invalidate("insights:summary:7")
await cache.invalidate_prefix("insights:")             # returns how many went
```

A `ttl` of `0` or less means "don't cache this": the key is removed and nothing is written.

## Where values live

`cache` is the shared instance, and it picks its backend from the project:

| Project | Backend | Shared across processes |
|---|---|---|
| Without the [Redis](../redis.md) component | A dictionary inside the process | No: each process has its own |
| With the Redis component | Redis, in its own logical database (`CACHE_REDIS_DB`, default `1`) | Yes: the webserver, worker, scheduler and CLI see the same values |

Values can be any Python object (models, dicts, lists). On Redis they are pickled, which is safe because only the app writes them.

For a private, per-process cache, construct one without a Redis URL. It always uses the in-memory dictionary, with expiry built in:

```python
from app.core.cache import CacheService

local = CacheService(default_ttl=30)
```

## Naming keys

Name keys `<area>:<thing>:<id>`, for example `insights:project:7`. The first two parts are the key's **family** (`insights:project`), and the Overseer groups the cache by family, so a consistent name is what makes the cache readable.

## Seeing what is in it

The Overseer's **Server > Cache** section (and the **Cache** tab in the Flet dashboard's backend dialog) shows:

- **Figures:** entries, bytes stored, families, and the hit rate.
- **Families, by room taken:** keys, size, share of the cache, average time left, and hit rate. A family that takes a lot of room and is rarely hit is the one to shorten or drop.
- **Largest keys**, with their time left.

Past 10,000 entries the view samples, and its numbers read as a floor (`10,000+`). Hits, misses and writes are counted per family in the process serving the page: with Redis the entries are shared, the counts are not.

`CacheService.entries()` and `CacheService.stats()` are what the view reads, if you want the same numbers elsewhere.

## Clearing

`cache.clear()` empties the cache's backend. On Redis that is the whole `CACHE_REDIS_DB` database. The worker's queues live in `REDIS_DB` and are untouched, but the traffic monitor's counters also live in the cache database and go with it.

## Short-lived processes

CLI commands and scripts should `await cache.aclose()` before exiting. Otherwise a Redis-backed cache prints a harmless "Event loop is closed" traceback at shutdown.

## Don't cache secrets

Nothing sensitive goes in the shared `cache`. With Redis it becomes a copy outside the process, persisted, and visible in the Overseer's Redis keyspace view. If a secret must be cached at all, use a private `CacheService()` as above.
