# Session State

Every Flet session needs a place to keep the resources that views share
within a session: the HTTP client, the theme manager, the signed-in user.
Aegis ships `SessionState` for exactly this, attached to `page.data` and
constructed once during bootstrap.

`SessionState` is the **only** intentional home for cross-view session
state. If a view needs to share something with the next view, it goes
here. If it can be re-fetched from the backend on demand, it does not.

## What `SessionState` holds

`SessionState` is a `dataclass` in
`app/components/frontend/state/session_state.py`:

```python
@dataclass
class SessionState:
    page: ft.Page
    api_client: APIClient
    theme_manager: ThemeManager | None = None
    current_user: dict[str, Any] | None = None   # when auth is enabled
    _data: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
```

| Field | Purpose |
| --- | --- |
| `page` | Backref to the Flet `ft.Page`. Convenient for helpers that take a `SessionState`. |
| `api_client` | The per-session [API client](api-client.md). One instance per Flet session. |
| `theme_manager` | The session's `ThemeManager` (theme tokens, dark/light, custom palette). |
| `current_user` | The signed-in user payload, populated by `is_authenticated()`. `None` until login. |
| `_data` / `get` / `set` | A typed-loose bag for ad-hoc session values that do not deserve a real field. Use sparingly. |

## Lifecycle

`SessionState` lives on `page.data["session_state"]` for the lifetime of
the Flet session. Two helpers manage it:

- **`init_session_state(page, *, api_client, theme_manager=None)`** is
  called once during the per-session bootstrap in
  `app/components/frontend/main.py`. It constructs the `SessionState`,
  stashes it on `page.data`, and returns it.
- **`get_session_state(page)`** is what views and controls call. It
  raises `RuntimeError` if the bootstrap never ran, which is the right
  failure mode: anything calling this expects a session to exist.

A typical view starts an action like this:

```python
from app.components.frontend.state.session_state import get_session_state

async def _reload(self) -> None:
    state = get_session_state(self.page)
    result = await state.api_client.get("/api/v1/insights/projects")
    ...
```

## Teardown

`SessionState` dies with the page. Flet does not expose a real
"session destroyed" hook in the current version, so eager teardown is
not always possible. The one code path that destroys it on purpose is
`clear_session_state(page)`, which:

1. Calls `await state.api_client.aclose()` to release the httpx pool.
2. Deletes `page.data["session_state"]`.

`clear_session_state` is **not** wired to `on_disconnect`. Flet fires
`on_disconnect` on transient WebSocket blips too; the session id is the
same and `on_connect` fires moments later against the same
`SessionState`. Closing the httpx client on every disconnect would leave
the post-reconnect call to `/auth/me` hitting a closed client.

In practice the underlying httpx connection pool drains via Python GC
when the page object is collected. The deterministic cleanup path
exists for cases where the application explicitly wants to tear down.

## Sign-out keeps `SessionState` alive

A common source of confusion: signing out **does not** call
`clear_session_state`. The Flet session is still connected; only the
auth state is being reset. `sign_out(page)` (in
`app/components/frontend/auth/session.py`):

1. POSTs `/api/v1/auth/logout` to revoke server-side.
2. Calls `api_client.clear_cookies()` to defang the local jar.
3. Sets `state.current_user = None`.
4. Routes the user to `/login`.

The same `SessionState` and `APIClient` instances live on, ready to be
used by the next sign-in.

## Storage: server vs browser

People conflate three different places state can live in a Flet app.
Knowing which is which makes the auth model a lot less mysterious.

| Storage | Lives in | Survives browser refresh? | Survives WebSocket drop? | Survives sign-out? | Use for |
| --- | --- | --- | --- | --- | --- |
| `SessionState` | Python process, `page.data["session_state"]` | No | Yes (same session id) | Yes | API client, theme manager, current user, anything that should outlive a view but not the session |
| `page.client_storage` | Browser `localStorage` | Yes | Yes | Yes | UI preferences (last-selected filter, sidebar open state). Survives refresh; **safe to read but never authoritative**. |
| HttpOnly cookie (`<project>_session`) | Browser cookie jar (HttpOnly) + httpx jar on server | Yes | Yes | No (cleared) | Auth and only auth. |

### Rule: do not put auth tokens in `client_storage`

`client_storage` is browser-side `localStorage`, readable by any JS
running on the page. Putting a session token there gives every script
on the page access to it. The HttpOnly cookie cannot be read by JS at
all, which is the whole reason it exists. The Aegis auth flow never
touches `client_storage`; the backend issues `Set-Cookie:
<project>_session=...` and the httpx client on the Python side carries it.
This pattern is also the same one you would use with any other Python
front end; the cookie does not care that Flet is rendering the UI.

### Rule: `SessionState` is in-memory only

`SessionState` lives in the Python process and dies with the session.
Anything in it is gone after a browser refresh. If a piece of state
needs to survive refresh:

- Persistent auth: the cookie handles it.
- User preferences: `page.client_storage` is the right tool.
- Anything else: it belongs in the backend (database, key-value store).
  The view re-fetches it on `on_enter` and `on_refresh`.

## Next Steps

- [API Client](api-client.md): the per-session `APIClient` that
  `SessionState` owns, and the cookie jar that makes auth work.
- [Events](events.md): how the page lifecycle interacts with
  `SessionState` (especially the refresh-or-redirect path on
  `on_connect`).
