# Auth Pages

When a project selects both the web frontend and the
[auth service](../../services/auth/index.md), it gets working auth pages wired
to the service's existing endpoints. Without the auth service, none of this is
generated: no auth routes, no auth templates, no auth JavaScript.

The pages are a UI over the auth service, not a second implementation of it.
Sessions, tokens, cookies, lockout, and rate limiting are all owned by the
service; the pages submit to it and render the results.

## What ships

| Page | Purpose |
|---|---|
| `/login` | Sign in. Redirects to `?next=` on success. |
| `/register` | Create an account; lands on the verify-pending page. |
| `/logout` | Drops the session and lands on `/`. |
| `/forgot-password` | Requests a reset email. |
| `/reset-password` | Consumes the emailed reset token. |
| `/verify-email` | Consumes the emailed verification token. |
| `/verify-pending` | "Check your inbox", with a resend button. |

All of them extend a shared split-screen shell
(`templates/pages/auth/_layout.html`) and use the form macros from
`templates/components/auth_macros.html`. The shell marks these pages
`noindex, nofollow`: reset and verification links carry one-time tokens in
their URLs, and crawlers must not snapshot them.

## Two deliberate design points

### Login and register are native form POSTs

The login and register forms submit as real browser form POSTs, not
`fetch()` calls. This is what makes the browser's save-password prompt work:
the browser needs to see a genuine password-field submit followed by a
redirect. A JavaScript submit handler that calls `fetch()` produces an
identical-looking flow and silently kills the prompt.

The page handlers delegate to the auth service's own login and register
endpoints rather than reimplementing them, so lockout, failed-attempt
tracking, audit events, and rate limits apply identically whether a user
signs in through the page or through the API.

!!! note "No save prompt on plain http://localhost"
    Chrome refuses to offer password saving on plain-HTTP localhost. That is
    a browser rule, not a bug in the pages. It works over HTTPS and on real
    hostnames.

### Session-expiry handling is single-flight

`static/js/auth.js` provides `fetchAuth()`, a `fetch()` wrapper that retries
once through the auth service's refresh endpoint on a 401, and a global htmx
hook that does the same for `hx-` requests.

The refresh is *single-flight*: one shared in-flight promise, no matter how
many requests hit a 401 at the same moment. This matters because the auth
service rotates refresh tokens with reuse detection. A page that fires several
authenticated requests in parallel would otherwise trigger several concurrent
refresh calls, and the second one would replay the token the first had just
rotated, which the service treats as theft and revokes the whole session.

The same renewal covers the other two ways a session runs out:

- **An htmx request** refused for an expired session gets a plain `401`,
  never a redirect: htmx would follow a redirect itself and swap the login
  page into the current one. The hook renews and reloads the page, or sends
  the whole page to sign in.
- **A full page load** lands on the sign-in page, which tries one silent
  renewal before showing the form and, if it works, goes back to `?next=`.
  So a returning visitor whose refresh cookie is still valid never sees the
  form. It tries at most once every few seconds, so a renewed session that
  pages still refuse cannot loop, and not at all when the form came back with
  a banner (a refused sign-in, a fresh registration). Overseer's own sign-in
  page (`/overseer/login`) behaves the same way and returns to the Overseer
  page asked for.

## Protecting a page

Page protection is opt-in, mirroring how
[API endpoints are protected](../../services/auth/index.md): a page without a
guard is public. To require a signed-in user, take the optional-user
dependency and bounce through the helper:

```python
from app.services.auth.deps import get_optional_user

@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(
    request: Request,
    user: User | None = Depends(get_optional_user),
) -> HTMLResponse:
    bounce = _current_user_or_redirect(request, user)
    if bounce:
        return bounce
    return templates.TemplateResponse(
        request=request, name="pages/settings.html", context={"user": user}
    )
```

Anonymous visitors are redirected to `/login?next=/settings` and returned
after signing in. The `next` value is validated server-side: only local paths
are followed, so the login page cannot be used as an open redirect.

There is deliberately no default-deny middleware. One protection mechanism,
attached where you want it, matching the rest of the stack.
