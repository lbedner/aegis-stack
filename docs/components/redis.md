# Redis

An in-memory store the rest of the stack builds on: the worker's job queues, the shared [cache](backend/cache.md), the traffic monitor's counters, and the health snapshot.

```bash
aegis add redis
```

## What you get

- **A Redis 7 service** in the compose stack (`redis:7-alpine`).
- **Settings:** `REDIS_URL` (default `redis://redis:6379`, the compose service), `REDIS_URL_LOCAL` for CLI commands run on the host, `REDIS_DB` and `CACHE_REDIS_DB`.
- **An Overseer page** (Components > Cache) with a keyspace map: every key grouped into the family that owns it, what each family is for, and how much room it takes.

## Logical databases

| Database | Setting | Holds |
|---|---|---|
| `0` | `REDIS_DB` | The worker's queues and job state, the health snapshot |
| `1` | `CACHE_REDIS_DB` | The shared cache and the traffic monitor's counters |

Keeping the cache in its own database means `cache.clear()` empties the cache without touching the queues.

## Memory and eviction

The dev service caps memory at 64 MB with `--maxmemory-policy volatile-lru`: under pressure, Redis evicts only keys that already expire (cache entries, job results, task records), least recently used first. Keys with no expiry, such as queued jobs, are never evicted; once nothing evictable is left, Redis refuses the write instead of silently dropping work. `allkeys-lru` would evict queued jobs, and a guard test keeps it out of the template.

## Seeing what is in it

- **Components > Cache** in the Overseer: the whole keyspace by family, the connection, and slow queries. The shared cache's entries show as one family, **Shared cache**, since services name their own keys.
- **Server > Cache**: the shared cache's families, sizes and hit rates. See [Cache](backend/cache.md).
