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

### The one modal, in one place

`hx_dialog(url, extra="")` is how anything opens the modal and
`hx_dialog_post(url)` how the form inside it posts back, so no template
names the target element. On the server, `dialog(request, template,
status_code, **context)` renders a dialog's body (a bare fragment, and a
422 re-renders the same partial with its errors) and `dialog_done(path,
toast)` ends a dialog form that made something: close, say so, navigate.

### Closing the dialog, moving on

`close_dialog(response)` closes the one modal after a successful in-dialog
action and `navigate(response, path)` sends the browser to `path` the htmx
way (`HX-Location`, swapped into `#app-content`). Both build on
`trigger(response, event, detail, header)`, which merges client events into
the `HX-Trigger` headers. `close_dialog` deliberately uses
`HX-Trigger-After-Settle`: a plain trigger fires before the swap, and a
response whose only content is rows out of band would then re-open the
dialog, empty.

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

Macros live under `templates/components/macros/`, one file per concern, one
macro per control. Import what you need:

```html
{% from "components/macros/form.html" import primary_button, or_divider %}
{% from "components/macros/table.html" import data_table %}
```

| File | Macros |
|---|---|
| `form.html` | `range_chips(ranges, days)` (the time-window row; see `web_frontend/ranges.py` for the windows), `action(label, attrs, tone, vals)` (the one compact button), and native controls that post or re-query through htmx: `field` (label + control via `{% call %}`, optional error), `text_input`, `money_input`, `textarea`, `select` (`blank=None` for no empty choice, `block=True` inside a field), `date_input`, `checkbox`, `search_input`; `primary_button`, `submit_button` (spinner; needs `loading` in Alpine scope); the Alpine `select_field`, `password_input`, `or_divider` |
| `layout.html` | `page_header(title, subtitle)` (the title row, with the caller's figures, chips and actions on the right), `figures(items)` (headline numbers), `stats_strip(cells)` (one bordered strip of N cells, each optionally a door), `ranked_rows(rows)` (name, count, amount, bar), `tab_bar` + `tab_item` (underline tabs), `chip(label, active, href, hx)`, `card` (titled section, body via `{% call %}`; a `None` title drops the header), `stat_tile(label, value, negative, caption, attrs)` (a caption line; `attrs` makes it a clickable cell), `progress(ratio, tone)`, `chart_panel`, `dialog`, `badge(label, tone)` (ok / warn / error / muted / accent), `dropdown` + `menu_item(label, attrs, danger)` (a `<details>` menu whose items close it), `confirm(title, body, url, label, method)` (a dialog body with one destructive verb), `theme_toggle`, `modal_scrim`, `popover_panel`, `hover_hint`, `info_tooltip` |
| `table.html` | `data_table(columns, rows, empty=..., row_id=...)`: declare columns (`key`, `label`, `kind` of text/money/date/int/status, `align`, `signed` or `toned` for money), hand over objects or dicts, formatting goes through the filters. `row_id` names each row so an action can swap it back; a `{% call(row) %}` block adds an actions column. `table_row(columns, row, id, oob, actions)` renders one row on its own, the usual answer to a row action. `pager`. The only table in the app. |
| `feedback.html` | `toast_region`, `empty_state`, `error_banner`, `oob(id, tag)` (an out-of-band sibling rendered next to a swapped row) |

`chart_panel(id, title, kind, data)` renders a canvas plus a JSON block;
`static/js/charts.js` mounts Chart.js over every `canvas[data-chart]` on
load and after each htmx settle, loading Chart.js on first use and reading
its palette from the theme tokens. `dialog()` is mounted once by the base
layout; a swap into `#dialog-body` opens it (pattern for any modal: `hx-get`
the body into that target).

### A table page

Declare the columns, hand over the rows the service already returns, and
let ``kind`` do the formatting. Nobody writes a ``<table>`` by hand.

```python
COLUMNS = [
    {"key": "date", "label": "Date", "kind": "date"},
    {"key": "name", "label": "Name"},
    {"key": "amount", "label": "Amount", "kind": "money", "align": "right"},
]

@router.get("/transactions", include_in_schema=False)
async def transactions(request: Request) -> Response:
    rows = await list_transactions()
    return render(request, "pages/transactions.html", {"rows": rows, "columns": COLUMNS})
```

```html
{% extends layout %}
{% from "components/macros/layout.html" import card %}
{% from "components/macros/table.html" import data_table %}

{% block app_content %}
{% call card("Transactions") %}
{{ data_table(columns, rows, empty="No transactions yet") }}
{% endcall %}
{% endblock %}
```

Rows may be objects or dicts. ``money`` reads the row's ``currency`` when it
has one, a blank value renders as a dash, and zero rows render the
``empty_state`` instead of an empty table.

### A dialog

``dialog()`` is mounted once by the base layout; it is a target, not a
component you instantiate. Any swap into ``#dialog-body`` opens it, Escape
or the close button closes it, and closing clears the body.

```html
<button type="button"
        hx-get="/transactions/42/edit" hx-target="#dialog-body">Edit</button>
```

The handler returns a bare fragment (a fragment-only route; no layout).
A form inside it posts back the same way, with ``hx-target="#dialog-body"``
so a 422 re-renders the form in place, and on success the handler swaps the
row it changed and adds an ``HX-Trigger`` to close the dialog or show a
toast.

## Filters

`filters.py` registers the formatting filters templates use, so numbers and
dates are never formatted by hand in markup:

| Filter | What it does |
|---|---|
| `money(cents, currency="USD")` | Integer minor units to `-$1,234.56`; honours the currency code. |
| `short_date(value)` | `Jul 15` this year, `Jul 15, 2025` otherwise; accepts dates, datetimes, ISO strings. |
| `pct(ratio, digits=0)` | A 0-1 ratio to `15%`. |
| `cents_to_input(cents)` | Minor units to a form value, `1,250.00`; the inverse of `money_to_cents` for pre-filling amount fields. |

## Template context

Three globals are available in every template, so routes never need to pass
them: `project_name`, `project_description`, and `static()` (covered in
[Asset pipeline](asset-pipeline.md)). Projects with the auth service also get
`auth_enabled` and `registration_enabled`. `render()` adds `layout` and
`current_path` to each page's context.

A fourth global, `hx_replace(url, target, oob=None)`, emits the attribute set
for "re-request this URL and replace `target` with the same element from the
response": filter forms, pagers, and list links that keep their state in the
URL. It always swaps `outerHTML`, because selecting the element you target
with the default inner swap nests a copy on every request.

```html
<form {{ hx_replace(request.url.path, "#register") }} hx-trigger="change">
<a href="{{ pager.next }}" {{ hx_replace(pager.next, "#items") }}>Next</a>
```

The htmx config in `base.html` sets `attributesToSettle` to an empty list.
htmx's settle step otherwise copies `class` and `style` from the old element
onto a swapped element with the same id, which undoes what Alpine's `x-show`
has just applied.

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
