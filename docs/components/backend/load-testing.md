# API Load Testing

Built-in API load testing against any FastAPI endpoint your generated
project exposes. Sibling to [worker load testing](../worker/extras/load-testing.md):
that one hammers the queue, this one hammers the API.

!!! info "Built-in"
    Ships in every generated project. No component to enable.
    Persists results in Redis when present; degrades cleanly without it.

## What You Get

- **Route auto-discovery** — every `APIRoute` in your FastAPI app is loadable, no per-endpoint registration
- **Concurrent orchestrator** — `httpx.AsyncClient` driven by a semaphore, capped at `--clients`
- **In-process or out-of-process** — `--in-process` runs against the app via `httpx.ASGITransport` for CI / quick checks; default hits a real running server
- **Path parameter substitution** — `--path-param key=value` resolves `{name}` placeholders before each request
- **Latency percentiles + status-code distribution + error sampling** — capped at 100 error samples per run
- **Live progress bar** in the terminal (when stdout is a TTY)
- **Result persistence in Redis** — 24h TTL, indexed by recency
- **Dashboard tab** — Backend modal → **Load Tests** shows recent runs with per-run drill-down

## Quick Usage

```bash
# See what's loadable
my-app api-load-test list

# Plain GET, in-process (no server needed)
my-app api-load-test run /health/ --requests 500 --clients 10 --in-process

# GET with a path parameter
my-app api-load-test run /api/v1/tasks/status/{task_id} \
    --path-param task_id=abc-123 \
    --requests 100 --clients 5 --in-process

# POST with payload
my-app api-load-test run /api/v1/tasks/enqueue \
    --method POST \
    --payload '{"queue": "load_test", "task": "ping"}' \
    --requests 200 --clients 10 --in-process

# Authenticated endpoint (token via header)
TOKEN=$(my-app auth login alice@example.com --print-token)
my-app api-load-test run /api/v1/users/me \
    --header "Authorization=Bearer $TOKEN" \
    --requests 200 --clients 5

# Recall recent runs
my-app api-load-test recent
my-app api-load-test results <test-id>
```

## `list` output

```
                           Discovered 21 routes
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┓
┃ METHOD ┃ PATH                              ┃ AUTH ┃ PARAMS  ┃ TAGS       ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━┩
│ GET    │ /health/                          │ no   │         │ health     │
│ GET    │ /api/v1/users/me                  │ yes  │         │ users      │
│ GET    │ /api/v1/tasks/status/{task_id}    │ no   │ task_id │ worker     │
│ POST   │ /api/v1/tasks/enqueue             │ no   │         │ worker     │
└────────┴───────────────────────────────────┴──────┴─────────┴────────────┘
```

- `METHOD` is colored per verb (blue / green / yellow / magenta / red for GET / POST / PUT / PATCH / DELETE)
- `AUTH` populated by inspecting each route's dependency tree for the project's `get_current_active_user` callable. Auth-less stacks read `no` everywhere
- `PARAMS` only appears when at least one route has `{...}` placeholders

## What works, what doesn't

| Endpoint shape | Example | Status |
|---|---|---|
| Plain GET, no params | `GET /health/` | works |
| GET with path param | `GET /api/v1/tasks/status/{task_id}` | works with `--path-param` |
| POST with static payload | `POST /api/v1/tasks/enqueue` | works with `--payload` |
| POST with dynamic payload | callable per request | field exists; resolver pending |
| Auth-gated | `GET /api/v1/users/me` | works with `--header "Authorization=..."` |
| SSE / streaming | `GET /events/worker/stream` | runs, but treats stream as one response (timeout risk) |
| WebSocket | (none today) | out of scope |

A first-class `--auth-as <username>` flag (CLI handles the login round-trip)
is on the roadmap.

## Reading results in Overseer

Click the **Backend** card on the dashboard → **Load Tests** tab. Each run
is a row in an expandable table:

- Top row: method, path, req/s, p95 ms, error %, "5 minutes ago"
- Expand a row for full latency percentiles, status code distribution,
  sampled errors, total duration, client count, test ID

Same data the CLI's `recent` command shows, with the addition of
per-request error samples.

## In-process vs out-of-process

| | `--in-process` (opt-in) | Out-of-process (default) |
|---|---|---|
| Transport | `httpx.ASGITransport` against the app object | Real HTTP over a socket |
| Server needed | no | yes (`my-app run` first) |
| Realism | skips uvicorn / keep-alive / kernel hop | exercises the whole stack |
| Use for | CI, regression gates, quick checks | production-shape numbers |

Throughput in-process is typically 2-5x what you'll see out-of-process
because there's no socket / no kernel hop. Don't compare across modes.

## Exit codes

- **0** — the run completed all its requests, regardless of how the
  endpoint responded. Endpoint errors are stats, not test failures.
- **2** — misconfiguration (e.g., unsubstituted `{...}` placeholders in the
  path). The error names the missing key.

Gate CI on response codes via `--json` + `jq` if you want strict
behaviour:

```bash
my-app api-load-test run /api/v1/users/me --json \
    | jq -e '.metrics.failure_rate_percent < 1.0'
```

## Programmatic use

```python
from app.services.load_test.api.service import APILoadTestService
from app.services.load_test.api.models import APILoadTestConfiguration

service = APILoadTestService()
result = await service.run(
    APILoadTestConfiguration(
        method="GET",
        path="/api/v1/users/{user_id}",
        path_params={"user_id": "u-9"},
        requests=200,
        clients=10,
        in_process=True,
    ),
    app=fastapi_app,
)
print(result.metrics.latency_ms_p95)
```

## Storage layout

When Redis is configured:

- `api_load_test:results:<test_id>` — full result, JSON-serialized, 24h TTL
- `api_load_test:recent` — sorted set of test IDs by start time; backs the
  `recent` / dashboard list views

Shared with the worker load-test service through
`app.services.load_test.common.storage.RedisResultStore`; only the
`key_prefix` differs.

## Limitations

- No automatic `--auth-as` round-trip yet. Use `--header "Authorization=..."`
  with a token obtained out of band
- No streaming-aware mode for SSE / chunked endpoints. Runs work, but
  each request is awaited to completion (inflates latency / risks timeouts)
- No run-to-run regression comparison built in. Persist results yourself
  via `--json` if you need historical trends
- HTTP only — no WebSocket or gRPC targets

## Related

Comparing two *configurations* rather than measuring one is a different
command: [`bench engines`](serving.md#measuring-it-yourself) boots the app
once per ASGI server and drives identical load at each. It takes the same
flags for describing a route, so anything you can load test here you can
benchmark there.
