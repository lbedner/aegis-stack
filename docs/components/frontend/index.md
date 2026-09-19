# Frontend Component

The **Frontend Component** is the user-facing surface of your Aegis project. It is
[Flet](https://flet.dev/) underneath, but Aegis ships an app factory, a routing
registry, a session-state container, and an HTTP client that turn Flet from
"render some controls" into a project you can actually structure.

!!! example "Musings: Why Flet (November 2025)"
    Most production UI work assumes a JavaScript stack: a separate repo, a
    separate build, a separate type system, a separate set of dependencies,
    and a serialization boundary in the middle.

    Flet collapses all of that. The widget tree runs in Python on the server.
    The browser holds a thin renderer that talks to it over a WebSocket. There
    is no `npm`, no bundler, no parallel set of `User`/`Project` schemas to
    keep in sync. The same Pydantic models that validate a FastAPI request
    body can be imported into a Flet view and used as-is.

    The other quiet payoff is multi-platform. The same Python code Flet renders
    in a browser also targets desktop and mobile through its native runtime.
    The project starts as a web app; the option to ship it elsewhere later
    is real, not aspirational.

## Why staying in Python matters

If you have already used FastAPI on the backend, the win is concrete:

- **Shared Pydantic models.** The schemas your API endpoints declare are
  importable from frontend code. No hand-written TypeScript mirror, no
  OpenAPI codegen step, no drift.
- **One toolchain.** `uv sync` installs both halves of the app. The linter,
  type checker, test runner, and Docker image are all the same.
- **Direct service access where it makes sense.** Frontend views can call
  Python service functions directly when they live in the same process. The
  default in Aegis is to still go through the HTTP API (so the same view
  works against a remote backend later), but the option is there.
- **Multi-platform target.** Flet renders to web today; desktop and mobile
  are reachable from the same Python source.

## What Aegis adds on top of Flet

Flet gives you `ft.Page`, controls, and an event loop. Aegis adds the
composition points a real project needs:

| Concern | Where it lives | Discovery |
| --- | --- | --- |
| App factory | `app/components/frontend/main.py` | Explicit |
| Page event handlers | `app/components/frontend/core/events.py` | Explicit |
| Route registry | `app/components/frontend/core/routing.py` | Explicit |
| View lifecycle ABC | `app/components/frontend/controls/views/base.py` | Inherit |
| Session state | `app/components/frontend/state/session_state.py` | Per-session |
| API client | `app/core/client.py` | Per-session |
| Theme manager | `app/components/frontend/theme_manager.py` | Per-session |
| Theme tokens | `app/components/frontend/theme.py` | Import |
| Reusable controls | `app/components/frontend/controls/*` | Import |

The split is asymmetric on purpose. Page-level events, the route table, and
the app factory are explicit because they describe the application's public
shape. Session state, the API client, and the theme manager are per-session
because each Flet session is its own world. Controls are just importable
modules; nothing magic.

## Anatomy of `app/components/frontend/`

```
app/components/frontend/
├── main.py              # create_frontend_app() + page bootstrap
├── theme.py             # ThemeManager + tokens
├── styles.py            # Style constants
├── core/
│   ├── routing.py       # ROUTE_TO_VIEW, route_change, view_pop
│   ├── events.py        # on_connect / on_disconnect / on_error / on_resize
│   └── routes.py        # Route constants (PUBLIC_ROUTES, LOGIN_ROUTE, ...)
├── auth/                # Login + register views, session helpers
├── state/
│   └── session_state.py # SessionState dataclass + helpers
├── controls/            # Reusable controls (buttons, cards, forms, ...)
│   └── views/
│       └── base.py      # BaseView ABC (on_enter / on_leave / on_refresh)
└── dashboard/           # Dashboard cards and feeds
```

## Next Steps

- [Architecture](architecture.md): how Flet actually runs. The server-side
  widget tree, the WebSocket bridge, and how it mounts onto FastAPI.
- [Routing & Views](routing.md): the route registry, `BaseView`, and the
  three lifecycle hooks that make navigation clean.
- [Session State](state.md): `SessionState`, the per-session HTTP client,
  and where each kind of state actually belongs (server, browser, cookie).
- [API Client](api-client.md): the per-session `httpx`-backed client and the
  cookie jar that makes auth Just Work.
- [Events](events.md): page lifecycle events vs. control events, and the
  task-cancellation discipline that keeps views clean.
- [Example](example.md): a small worked view, end to end.
