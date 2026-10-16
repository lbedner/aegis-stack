# Redis

An in-memory store the rest of the stack builds on: the worker's job queues, the shared [cache](backend/cache.md), the traffic monitor's counters, and the health snapshot.

```bash
aegis add redis
```

## What you get

- **A Redis 7 service** in the compose stack (`redis:7-alpine`).
- **Settings:** `REDIS_URL` (default `redis://redis:6379`, the compose service), `REDIS_URL_LOCAL` for CLI commands run on the host, `REDIS_DB` and `CACHE_REDIS_DB`.
- **An Overseer page** (Components > Cache) with a keyspace map: every key grouped into the family that owns it, what each family is for, and how much room it takes. Pick a family to see how much it holds and has passed through, in its owner's words.

## Logical databases

| Database | Setting | Holds |
|---|---|---|
| `0` | `REDIS_DB` | The worker's queues and job state, the health snapshot |
| `1` | `CACHE_REDIS_DB` | The shared cache and the traffic monitor's counters |

Keeping the cache in its own database means `cache.clear()` empties the cache without touching the queues.

## Memory and eviction

The dev service caps memory at 64 MB with `--maxmemory-policy volatile-lru`: under pressure, Redis evicts only keys that already expire (cache entries, job results, task records), least recently used first. Keys with no expiry, such as queued jobs, are never evicted; once nothing evictable is left, Redis refuses the write instead of silently dropping work. `allkeys-lru` would evict queued jobs, and a guard test keeps it out of the template.

## Seeing what is in it

- **Components > Cache** in the Overseer: the whole keyspace by family, the connection, and slow queries. The shared cache's entries show as one family, **Shared cache**, since services name their own keys; the live charts' history (`app.core.series_keys`) shows as its own.
- **Slow queries** say what each command touched: its key, as Redis names a command's keys (`COMMAND GETKEYS`), and the family that key belongs to, so `ZRANGEBYSCORE series:containers:worker:...:cpu` reads as **Chart history**. A command without a key (`KEYS`, `INFO`) touched none.
- **A family, picked**, says what it is for and how it is doing, read from the data itself, nothing stored: a stream's every entry since it began (Redis counts them), how many came in the last minute and hour, drawn a minute at a time, and each reader group with how far behind it is; a sorted set scored by time the same, its oldest and newest as times; a list's depth; counters stored as strings added up. Each figure counts in the family's own word (`KeyFamily(..., holds="event")`), else its type's (entries, members, items). Then its newest key's entries, a stream's as their fields and when each came. A family holding a credential (`peek=False`) is named, never read.

To have your own keys mapped, declare them beside the code that writes them and list the module in `redis_keys.OWNERS`:

```python
from app.core.key_family import KeyFamily

REDIS_KEYS = (
    KeyFamily(
        "orders:events",
        "stream",
        "Order events",
        "Every order placed, paid or refunded, for the receipts worker",
        "Orders service",
        columns=("Entry", "Event"),
        holds="event",
    ),
)
```
- **Server > Cache**: the shared cache's families, sizes and hit rates. See [Cache](backend/cache.md).
