# Live Updates

Use a server-rendered snapshot followed by Server-Sent Events (SSE) for
one-way live status. Overseer's sidebar and Server Overview are the first
examples.

## Contract

1. The normal GET returns the full page with the installed component catalog
   and the last completed health snapshot. On a cold start, status shows as
   pending so a slow probe cannot hold up page rendering. Links work without
   JavaScript.
2. One authenticated SSE connection belongs to the stable page shell, outside
   the htmx fragment target. Navigation swaps the page content without
   reconnecting the stream.
3. The stream sends a complete baseline on connect or reconnect, then named
   events only when state changes. A browser that missed events catches up from
   the next baseline.
4. A single sampler per web process collects health for all connected viewers.
   Subscriber queues hold only the newest complete state. A slow viewer cannot
   make memory use grow without bound.
5. SSE comments keep the connection alive; they do not run a health check.
   Connections expire periodically so authentication is checked again.

The Overseer implementation is `app/components/web_frontend/overseer_events.py`.
Its producer uses the existing cached `get_system_status()` result. Page
navigation reads `last_system_status()` and the registered health check names,
so changing sections never triggers a health walk. The SSE sampler performs
the first collection after a cold page load. The stream authenticates before
opening and closes its database session before it starts sending events.

The sidebar listens with htmx's SSE extension and `sse-swap` on each status
indicator. A component page's sub-menu shows the same status dot and listens
for the same event, so the two never disagree. The Server Overview listens for
`server-overview`, which replaces its figures and resource panel when they
change. The other Server sections (Performance, Traffic, Load Tests, Routes,
Lifecycle) are ordinary HTMX requests that read their sources when opened. Each event
contains server-rendered HTML. Every SSE target sets `hx-target="this"` so
it cannot inherit a surrounding navigation link's `hx-target`. The browser
needs no second status model or JSON-to-DOM mapping.

## Deployment boundary

The current fanout is process-local: each web process with viewers runs one
sampler. This removes per-viewer polling without requiring Redis in a basic
stack. In a deployment with many web processes, a shared publisher and Redis
Streams can replace the process-local producer while retaining the same page,
SSE route, event names, and snapshot contract. Worker activity already uses
Redis Streams and SSE when the worker component is installed.

SSE does not make external health checks event-driven. Database reachability,
CPU, and similar values still need a bounded server-side sampling cadence.
Jobs and worker lifecycle events can publish immediately because those changes
already originate inside the application.
