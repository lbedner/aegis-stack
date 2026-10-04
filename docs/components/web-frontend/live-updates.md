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
6. Every event stream's first frame is an `id:` naming its connection record
   (the connections middleware adds it). The browser's own retry sends it back
   as `Last-Event-ID`, which is how Server > Connections tells a reconnect from
   a new page opening the same stream.
7. A stream that may go quiet for a while (followed log lines) is wrapped in
   `overseer_live.heartbeat(frames)`, which sends an SSE comment every 15
   seconds without a frame, ends the stream at the expiry above, and closes
   its source when the browser leaves.

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

## Time series and live charts

Anything the app polls or counts can be kept as a time series and charted
live. A sampler names what it reads; `read` returns a `Sample`: numbers by
series name, and the reading as a whole for the views that show it:

```python
from app.core.series import Sample, Sampler

async def queue_depths() -> Sample:
    depths = {"system": 12, "media": 0}
    return Sample({f"{q}:depth": n for q, n in depths.items()}, latest=depths)

SAMPLERS = [Sampler("containers", ui_runtime.sample), Sampler("queues", queue_depths)]
```

Samplers are listed in `app/services/system/samplers.py` and run in the
webserver from startup. Each tick's numbers are kept for an hour in the shared
cache under `series:<sampler>:<name>` (Redis when the stack has it, so every
process reads the same history; process memory otherwise), listed in an index
set per sampler so reads never scan the keyspace. One process samples each
tick.

Polling costs only while someone looks. A view reads the sampler's last
reading (`series.latest`) and marks it watched (`series.watch`); a watched
sampler reads every `interval` (a second), an unwatched one every
`idle_interval` (15 seconds), enough to keep the charts' history. Every viewer
is served from the one reading, so ten open pages cost what one does.
Something that happens rather than something polled is a point of its own:
`series.record("llm:qwen2.5:7b:latency", 1.4)`, as every LLM call does when it
finishes.

What Overseer samples today: the containers behind each page, Ollama on the
host (the Inference page, the Flet Ollama modal, and the model loads and
evictions its Activity tab lists), the Redis keyspace map, and the worker
queues (each queue's waiting and finished counts, so its rate and drain read
the same for every viewer and survive a reconnect). A page whose server can
run outside Docker registers its own note and charts beside its sampler
(`samplers.HOSTS`, read through `ui_runtime.host_of`), so a stack without
that component carries none of them.

`series.read(prefix, window)` gives a window back and `series.chart(...)`
turns it into `chart_panel` data, one line per series on the times they
share, the axis spanning the window up to now. A window longer than
`MAX_POINTS` seconds is averaged into buckets on fixed boundaries, so each
bucket keeps its place as the window moves. The windows a chart offers are
`series.WINDOWS` (15m, 30m, 1h, labelled like every other range row), picked
with `range_chips` on the web and `DateRangeChips` in Flet; the choice lives
in the query string (`?window=1800`) and the section's stream follows it.

A chart goes live with `chart_panel(..., live="<event>")` inside an element
with `sse-connect`: the stream re-sends `chart_data(id, data)` as that event
and `charts.js` updates the drawn chart in place: a time chart (`"x": "time"`)
slides along, its oldest points leaving and new ones joining the same line.
`chart_panel(..., empty="...")` is said over a chart with nothing in its
window. `fragments_events` sends several fragments (a table and its charts) on
one stream. The data's `"format"` (`percent`, `bytes`, `seconds`, `money`)
reads the same in the Flet charts (`LineChartCard.from_chart`).

Overseer's Container section is the first user: CPU and memory per container
over the last 15 minutes. A server outside Docker charts what it reports of
itself instead (`ui_runtime.host_of`): Ollama on the host shows the memory each
loaded model holds (the inference sampler, which also serves the Inference
page's Models table) and each call's tokens per second and latency.
