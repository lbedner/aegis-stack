# Health

Every component and service reports its health, and Overseer shows it: on the
Overview's cards and map, in the sidebar beside each page, and on each part's
own page. The same reports are `GET /health/detailed`, the `health` tool
Illiana and MCP clients use, and a node's `now` in the [Twin](twin.md).

## How it works

```
 startup                          running
 -------                          -------
 component / service              sampler (one per web process)
   | registers / declares HEALTH    | runs every registered check
   v                                v
 health registry  ------------>  SystemStatus (a tree)
                                    | only what changed, over SSE
                                    v
                                 open Overseer pages
```

1. **Registration.** As the app starts, each component registers, and each
   service declares, its health check with the health registry.
2. **Aggregation.** The registry runs every check and gathers the results into
   one tree: the app, its components and services, and their sub-checks.
3. **Push.** One sampler per web process reads the tree and pushes to open
   Overseer pages only when a status changes; a page that connects or
   reconnects gets the whole snapshot first. Each viewer holds only the latest
   state, so a slow tab cannot grow memory.

## Statuses

| Status | Meaning |
|--------|---------|
| **Healthy** | Fully operational |
| **Info** | Worth knowing, not a problem |
| **Warning** | Operational, with issues |
| **Unhealthy** | Down or failing |

A parent takes the worst of its children: any child unhealthy makes it
unhealthy; else any warning makes it a warning; else any info makes it info;
else it is healthy.

## Adding your own

A check is an async function that returns a `ComponentStatus`: a status, a
one-line message (the health line on its card), and any figures for the card
in `metadata`. A service keeps it in its `health.py`:

```python
from app.services.system.models import ComponentStatus, ComponentStatusType


async def check_orders_service_health() -> ComponentStatus:
    pending = await count_pending_orders()
    return ComponentStatus(
        name="orders",
        status=ComponentStatusType.WARNING if pending > 100 else ComponentStatusType.HEALTHY,
        message=f"{pending} pending",
        metadata={"pending": pending},
    )


HEALTH = check_orders_service_health
```

`HEALTH` is what registers it: at startup every service's `health.py` is
found on disk and its `HEALTH` registered under the service's folder name,
an app's own service's too, so no framework file changes.

A component instead calls `register_health_check(name, check)` from a
startup hook. Keep a check
fast (the sampler runs every check), and return `UNHEALTHY` with the error as
the message rather than raising.
