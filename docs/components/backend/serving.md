# ASGI Server

!!! example "Musings: On Not Picking a Winner (September 18th, 2026)"
    [Granian](https://github.com/emmett-framework/granian) is faster. I measured it, it's about 1.5x on a trivial route, and it's the most mature of the new crop by a distance. So the obvious move is to swap the default and move on.

    I'm not doing that, and it took me a minute to articulate why. There are two camps forming underneath Python web serving right now and they're both moving fast. [Giovanni Barillari](https://github.com/gi0baro) is going Rust: granian, [rloop](https://github.com/gi0baro/rloop), and now [TonIO](https://github.com/gi0baro/tonio), which walks away from asyncio entirely. [Marcelo Trylesinski](https://marcelotryle.com/), who maintains [uvicorn](https://uvicorn.dev/), is rebuilding its two speed dependencies in Zig: [zuvloop](https://github.com/Kludex/zuvloop) for [uvloop](https://github.com/MagicStack/uvloop), [zttp](https://github.com/Kludex/zttp) for [httptools](https://github.com/MagicStack/httptools). I benchmarked uvicorn on zuvloop and it ate 38% of granian's lead, taking it from 1.54x down to 1.28x. Granian is still ahead. But that's a three-day-old 0.0.x library with the other half of the pair not even wired in yet, and it's the slope that matters, not today's number.

    So whoever is fastest today is not who's fastest in six months, and Aegis Stack is supposed to be about options. If I collapse this to one server because of one benchmark on one endpoint, I've deleted the thing I'm actually selling. The default stays uvicorn because that's what works everywhere, and granian is one flag away because sometimes you want it.

    The part that surprised me: the loop barely matters under granian and matters a lot under uvicorn. Makes sense once you think about where the Rust is. And rloop, which I was excited about, came out a wash. Still glad it's reachable.

    What I don't have yet is the honest answer to "does this matter for my app". The engine gap shrinks the moment your handler waits on a database, which is most handlers. That's why the benchmark takes any route instead of hardcoding one. Go measure your own stuff.

Two independent choices sit underneath your FastAPI app: the **ASGI server**
that speaks HTTP, and the **event loop** it runs on. Both default to what
Aegis has always shipped, and both are one flag away from something else.

!!! info "Built-in"
    Ships in every generated project. No component to enable. Defaults are
    unchanged from before this existed: uvicorn, on uvloop where it is
    installed.

## Quick Usage

```bash
make serve                     # uvicorn on uvloop (the default)
make serve ENGINE=granian      # this run only
make serve LOOP=rloop          # granian only
make serve LOOP=zuvloop        # uvicorn only, 3.14+, reload off
make bench-engines             # measure both on your own routes
```

Nothing is persisted by a flag. For a deployment, set `WEBSERVER_ENGINE`
and `WEBSERVER_LOOP` in the env file alongside every other deploy setting.

## The Engine

| | [uvicorn](https://uvicorn.dev/) | [granian](https://github.com/emmett-framework/granian) |
| --- | --- | --- |
| Written in | Python + C | Rust |
| Status | default | opt-in |
| Free-threaded wheels | not verified | yes, since 2.0 (upstream calls it experimental) |

Granian runs **1.4x uvicorn on Python 3.11 and 3.12, and 1.5x on 3.13 and
3.14**, on a trivial route. Measured on a generated 0.13.0 base stack for
each Python version Aegis supports, `GET /health/`, 5,000 requests, 50
clients, best of 3, two passes averaged, one Apple M4 Max session:

| Python | uvicorn + uvloop | uvicorn + asyncio | granian + uvloop | granian + asyncio | granian vs uvicorn |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3.11 | 4,980 | 4,520 | 6,925 | 5,632 | 1.39x |
| 3.12 | 5,008 | 4,692 | 6,838 | 6,025 | 1.37x |
| 3.13 | 5,277 | 5,447 | 8,442 | 7,404 | 1.55x |
| 3.14 | 5,050 | 5,310 | 8,130 | 6,954 | 1.53x |

The last column compares each engine on its faster loop. Uvicorn barely
moves across versions; granian gains about 20% from 3.13 on, which is where
the gap widens. Re-running moves any one number a few percent, so read the
ratios, not the digits.

That number shrinks as your handler does real work. The same benchmark on
`/health/detailed` gives 1.35x, and a route that waits on the database will
compress further, because at that point you are timing PostgreSQL rather
than the server. **The ratio is a property of your app, not of the engine**,
which is why `bench-engines` takes any route rather than hardcoding one.

## The Event Loop

A separate axis, and it does not behave the way its reputation says. From
the table above:

- **Under granian, uvloop wins on every version**, by 12% to 25% over
  asyncio. Granian hands each request from its Rust runtime to the Python
  loop, and uvloop's C implementation of that hand-off is the likely
  difference.
- **Under uvicorn, uvloop's lead has gone.** It is about 10% ahead of
  asyncio on 3.11, 7% on 3.12, level on 3.13, and a few percent *behind* on
  3.14. The standard library's asyncio got faster in every one of those
  releases and uvloop did not. HTTP parsing is httptools either way, so the
  loop only moves bytes, and there is little left for it to win.

`auto` still resolves to uvloop: it is the clear winner under granian, the
faster choice under uvicorn on 3.11 and 3.12, and at most a few percent
behind anywhere else.

### What's out there

| Loop | Built on | Status | Installed by default |
| --- | --- | --- | --- |
| [asyncio](https://docs.python.org/3/library/asyncio-eventloop.html) | the standard library | always available | yes |
| [uvloop](https://github.com/MagicStack/uvloop) | Cython on libuv | mature, the usual default | yes |
| [rloop](https://github.com/gi0baro/rloop) | Rust on mio | 0.5.x, Unix only | no |
| [zuvloop](https://github.com/Kludex/zuvloop) | Zig on libuv | 0.0.x, Python 3.14+, uvicorn only | on 3.14+ |

### What each engine accepts

| | asyncio | uvloop | rloop | zuvloop |
| --- | --- | --- | --- | --- |
| uvicorn | yes | yes | no | yes, on 3.14+ |
| granian | yes | yes | yes | no |

A combination that cannot work fails at startup, naming what the running
engine accepts.

**rloop** works fine under granian and is simply not faster. Five samples
each on `/health/` put it level with uvloop, median 8,029 against 8,207,
which is inside the run-to-run spread. That is one endpoint, so it is
evidence rather than proof, but there is no reason to reach for it yet.

**zuvloop** comes from [Marcelo Trylesinski](https://marcelotryle.com/),
who maintains uvicorn, and it is half of a pair: zuvloop replaces uvloop,
[zttp](https://github.com/Kludex/zttp) replaces
[httptools](https://github.com/MagicStack/httptools). Those are exactly
uvicorn's two speed dependencies, both being rewritten in Zig.

Measured through this entrypoint, one session, best of three, `GET
/health/` at 3000 requests and 50 clients:

| | req/s | |
| --- | --- | --- |
| uvicorn + uvloop | 4,919 | |
| uvicorn + zuvloop | 5,927 | +20% |
| granian + uvloop | 7,561 | |

So zuvloop closes **38%** of the gap and granian stays **1.28x** ahead,
down from 1.54x. Worth having on the uvicorn side, and not a reason to
stop reaching for granian.

```bash
make serve LOOP=zuvloop      # uvicorn only, Python 3.14+, reload off
```

Three things to know before you reach for it:

- **Python 3.14 or newer.** The dependency carries a marker
  (`python_version >= '3.14'`), so older projects resolve without it
  rather than failing to install, and asking for it anyway fails at
  startup with a sentence rather than an `ImportError`.
- **It cannot run with reload.** Uvicorn's reloader is a supervisor that
  spawns child processes, so there is no coroutine to hand zuvloop.
  Develop on uvloop, deploy on zuvloop.
- **`auto` will never pick it.** It is 0.0.x. It stays something you ask
  for by name.

Granian cannot use it at all. Its `Loops` enum has no `zuvloop` member,
and zuvloop ships no `EventLoopPolicy`, so there is no back door through
granian's asyncio builder either.

### `auto` is resolved by the app, deliberately

`WEBSERVER_LOOP` defaults to `auto`, which resolves to uvloop when it is
installed and asyncio otherwise. Aegis resolves this itself rather than
passing `auto` down to the server, and that is not an accident.

Granian's own `auto` prefers rloop the moment rloop is importable. Left
alone, a transitive dependency pulling rloop into your tree would move
production onto an alpha event loop with no code change, no flag, and
nothing in the logs. Resolving here means the loop is always a decision, and
the startup line always names it:

```
Starting Aegis Stack Web Server (granian on uvloop)...
```

The compatibility matrix lives in `app/core/loops.py`, in one place, because
it is the part of this that grows.

## Measuring It Yourself

`bench engines` boots your app once per engine and drives identical load at
each, so both numbers share a client, a route and a machine.

```bash
my-app bench engines
my-app bench engines --path "/api/v1/jobs/{job_id}" --path-param job_id=abc-123
my-app bench engines --method POST --path /api/v1/things --payload '{"name":"x"}'
my-app bench engines --path /api/v1/private/ --as-admin
my-app bench engines --loop rloop -n 10000 -c 100 --rounds 3
```

It takes the same flags [`api-load-test run`](load-testing.md) does, because
it is the same vocabulary for describing a route.

```
engine    loop             req/s      p50 ms      p95 ms      p99 ms    failed
------------------------------------------------------------------------------
uvicorn   uvloop           4,919       10.00       11.00       12.00         0
granian   uvloop           7,561        7.00        8.00        8.00         0

granian is 1.54x uvicorn on this route.
```

### Drivers

The load generator matters as much as the server, because a client that
cannot saturate reports every engine as equal. Three, tried in order, and
the output always names the one that ran:

| Driver | When | Notes |
| --- | --- | --- |
| `ab` | a local [ApacheBench](https://httpd.apache.org/docs/2.4/programs/ab.html) exists | bundled on macOS |
| `ab-docker` | no local `ab`, but Docker | the official `httpd:alpine` image |
| `api-load-test` | neither, or a method `ab` cannot issue | **cannot saturate** |

`ab` is absent from most Linux, which is CI, most containers, and plenty
of laptops. Docker is already required for a generated project, so the
tool that tells you to measure your own routes should not itself need a
system package first.

On Linux the container runs with `--network host`, so there is no NAT
between it and the server and it should measure close to a local `ab`.
That is reasoning rather than a measurement: it was written on macOS,
where Docker NATs through a VM. **That** path is measured, and the NAT
costs several times the absolute throughput while leaving the ratio
between engines intact, 1.53x against 1.54x native.

Either way, treat a container number as comparable only to another
container number.

The last row is the honest dead end: the project's own load-test client
tops out near 500 req/s, well under what either engine serves, so it
reports them as equal no matter what. The output says so when it happens.

## When To Choose Granian

Reach for it when a benchmark on **your** routes shows a gap worth having,
which in practice means routes that are mostly serving rather than mostly
waiting.

The two engines are not drop-in equivalents. Three differences are worth
knowing before you flip the flag, in rough order of how likely they are to
bite you.

### WebSocket keepalive

| | behavior |
| --- | --- |
| uvicorn | pings every 20s, drops the socket if the pong is late |
| granian | sends no server-initiated ping at all |

Uvicorn's ping is why the uvicorn path sets `ws_ping_interval=None`: behind
a reverse proxy the pong arrives late and the connection dies mid-session.
Granian has no equivalent knob because it has no equivalent behavior.
Nothing to configure, nothing to time out.

### Reload behavior in development

Granian's `respawn_failed_workers` defaults to **off**, so a worker that
dies on reload is never replaced: one transient broken save stops the dev
server, prints no error line, and leaves it stopped until you restart by
hand.

Aegis owns the granian invocation, so it sets `respawn_failed_workers`
rather than only warning about it: on in dev, off in production where the
container healthcheck already restarts a dead server and respawning would
hide a crashloop.

**That flag does not fully close the hole, and it is worth knowing which
half it leaves open.** Tested by saving a syntax error into a running dev
server: granian tore the server down anyway, and repairing the file did
not bring it back, because nothing was left watching. The flag covers a
worker that dies while *running*; a worker that dies on the way *up*, as
a bad import does, still takes the server with it.

So under granian, treat a dev server that has gone quiet as needing a
restart. Uvicorn's reloader retries on the next save and does not.

### `http.response.pathsend`, if you write middleware

| | advertises the extension |
| --- | --- |
| uvicorn | no |
| granian | **yes** |

A server offering `pathsend` receives a file *path* rather than a response
body for static files, and hands the sending off to itself. That is faster,
and it means any middleware rewriting response bodies has to handle
`http.response.pathsend` as well as `http.response.body`.

Miss it and the symptom is not subtle: the middleware forwards a body with
no start, and every affected page returns 500. That is not hypothetical,
it is what happened to the dashboard the first time this app was served
under granian.

The middleware Aegis ships handles it, and a test enforces that rather
than trusting the docs: anything under
`app/components/backend/middleware/` that touches `http.response.body`
must also handle `http.response.pathsend`. Your own middleware is outside
that net, so this is the one to remember.

## Next Steps

- [API Load Testing](load-testing.md) — capacity of a single route
- [Performance Middleware](middleware/performance.md) — per-route timing from inside the app
