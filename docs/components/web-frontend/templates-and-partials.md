# Templates and Rendering

## The base layout

Every page extends `templates/base.html`, which owns the document skeleton and
exposes these blocks:

| Block | Use |
|---|---|
| `title` | Browser tab title. Defaults to the project name. |
| `favicon` | Override to swap the shipped SVG favicon. |
| `head_extra` | Per-page head additions: meta description, OG tags. |
| `navbar` | Replace the default bar (the landing does). |
| `page_body` | The whole `<main>` wrapper. Rarely overridden. |
| `content` | The page body, inside `<main id="app-content">`. |
| `footer` | Empty by default. |
| `scripts` | Per-page scripts, loaded after `app.js`. |

Override `content` for an ordinary page. Reach for `page_body` only when a
page needs to replace the entire main wrapper (the auth pages do, for their
split-screen shell).

The base loads htmx, the htmx SSE extension, and Alpine from pinned CDN URLs.
The Alpine *collapse plugin* is loaded before Alpine core, deliberately: Alpine
registers plugin directives at init, so loading core first leaves `x-collapse`
silently dead. The SSE extension is loaded after htmx core for the mirror
reason: it registers against the global htmx defines.

## One route, two render paths

A view has one URL and one template. Whether the browser gets a full page or
just the part htmx will swap in is decided per request by
`rendering.render()`:

```python
from app.components.web_frontend.rendering import render
from fastapi import APIRouter, Request
from starlette.responses import Response

router = APIRouter()


@router.get("/accounts", include_in_schema=False)
async def accounts(request: Request) -> Response:
    rows = await load_accounts()
    return render(request, "pages/accounts.html", {"rows": rows})
```

The page template ends with `{% extends layout %}` and fills one block:

```html
{% extends layout %}

{% block title %}Accounts - {{ project_name }}{% endblock %}

{% block app_content %}
<h1>Accounts</h1>
...
{% endblock %}
```

`render()` sets `layout` to `layouts/page.html` on a cold load, which places
`app_content` inside the base layout's `<main id="app-content">`, and to
`layouts/fragment.html` when the request carries `HX-Request: true`, which
renders the block bare. A boosted request (`hx-boost`) still gets the full
page, since it replaces the whole body. The response carries `Vary:
HX-Request` so a cache never serves a fragment to a cold load.

A link that works both ways points its `href` and its `hx-get` at the same
URL:

```html
<a href="/accounts"
   hx-get="/accounts" hx-target="#app-content" hx-push-url="true">Accounts</a>
```

`render()` also takes `status_code`. A form handler that fails validation
re-renders the form template with `status_code=422`; the base layout's htmx
configuration lets a 422 swap, so the errors land where the form was.

To give an app its own chrome, such as a sidebar shell, add a sibling under
`templates/layouts/` that extends `base.html` and keeps the `app_content`
block, and point `rendering.PAGE_LAYOUT` at it.

### Fragment-only routes

Some responses are only ever swapped in: a table row after an edit, a search
result list, a dialog body. Those handlers return the fragment directly with
`templates.TemplateResponse` and live under `routes/partials/`, mounted with a
`/partials/...` prefix in `create_web_frontend_app()`. Fragment templates have
no `{% extends %}`.

## Feedback

### Toasts

A route attaches a toast to any response:

```python
from app.components.web_frontend.rendering import render, with_toast

response = render(request, "pages/accounts.html", {"rows": rows})
return with_toast(response, "Account saved")
```

`with_toast` writes an `HX-Trigger` header. htmx raises a `toast` DOM event,
and the region the base layout mounts (`toast_region()` from
`components/macros/feedback.html`) shows it: four seconds for a confirmation,
eight for `tone="error"`, dismissable early. No reload, no storage. The
header merges with triggers already on the response.

Server and network failures need no code: the base layout's htmx
configuration stops 4xx/5xx bodies from swapping, and `app.js` turns the
resulting `htmx:responseError` and `htmx:sendError` events into an error
toast.

### Empty states and form errors

`components/macros/feedback.html` also ships `empty_state(title, hint=None)`
for a list with nothing in it and `error_banner(errors)` for a form's
validation errors. `error_banner` renders nothing for an empty list, so a form
template calls it unconditionally.

## Two load-bearing rules

Both of these exist because of real failure modes. Keep them.

### Fragments carry no inline scripts

Browsers do not run `<script>` tags injected via `innerHTML`, which is how
htmx inserts a swapped fragment. Rather than re-executing them (which also
rules out a Content Security Policy), behaviour that needs JavaScript is
registered once from a static file and keyed off DOM events or Alpine
components. The auth pages are the worked example: each page's `x-data` names
an `Alpine.data(...)` component registered in `static/js/auth.js`.

### htmx history is disabled

The base layout sets `historyCacheSize: 0` and `refreshOnHistoryMiss: true`
in the `htmx-config` meta tag.

htmx's default back-button behavior snapshots the live DOM into localStorage
and re-injects it on history navigation. This DOM is full of Alpine-expanded
templates (`x-if`/`x-for` clones, `x-teleport` copies). Restoring a snapshot
makes Alpine re-expand already-expanded templates, duplicating page content
once per back/forward press. With the cache disabled every restore is a miss,
and a miss is a clean full-page load. Back and forward still work; they just
re-render instead of restoring a snapshot.

## The macro kit

`templates/components/macros.html` ships reusable macros. Import what you
need:

```html
{% from "components/macros.html" import primary_button, or_divider %}
```

| Macro | What it is |
|---|---|
| `modal_scrim` | Full-bleed dismiss layer behind a modal. |
| `popover_panel` | The one tooltip panel every hover hint uses. |
| `hover_hint` | Dotted-underline term with a hover definition. |
| `info_tooltip` | Small `?` icon with a click-triggered popover. |
| `primary_button` | The teal action button. |
| `submit_button` | Primary button with a loading spinner; needs `loading` in Alpine scope. |
| `select_field` | Themed combobox replacing the native `<select>`. |
| `password_input` | Password field with a show/hide toggle. |
| `or_divider` | "or" hairline between alternative actions. |

Macros that take a body use `{% call %}`:

```html
{% call info_tooltip() %}<p>Explanation here.</p>{% endcall %}
```

## Filters

`filters.py` registers the formatting filters templates use, so numbers and
dates are never formatted by hand in markup:

| Filter | What it does |
|---|---|
| `money(cents, currency="USD")` | Integer minor units to `-$1,234.56`; honours the currency code. |
| `short_date(value)` | `Jul 15` this year, `Jul 15, 2025` otherwise; accepts dates, datetimes, ISO strings. |
| `pct(ratio, digits=0)` | A 0-1 ratio to `15%`. |

## Template context

Three globals are available in every template, so routes never need to pass
them: `project_name`, `project_description`, and `static()` (covered in
[Asset pipeline](asset-pipeline.md)). Projects with the auth service also get
`auth_enabled` and `registration_enabled`. `render()` adds `layout` and
`current_path` to each page's context.

## Testing pages

The generated project ships a web test kit under `tests/web/`:

- the `hx` fixture, a test client that sends `HX-Request: true`, so every
  route is tested both ways alongside the plain `client`;
- `add_template(name, source)`, which registers a throwaway page against the
  real environment for one test;
- `dom.select`, `one`, `none` and `text`, so assertions target elements
  rather than substrings of the response.

```python
from tests.web.dom import none, one, text

def test_accounts_fragment(hx):
    fragment = hx.get("/accounts").text
    assert text(one(fragment, "h1")) == "Accounts"
    none(fragment, "html")
```
