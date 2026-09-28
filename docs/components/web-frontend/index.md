# Web Frontend Component

The **Web Frontend Component** adds server-rendered pages to your project:
[Jinja2](https://jinja.palletsprojects.com/) templates,
[htmx](https://htmx.org/) for interactivity, [Alpine.js](https://alpinejs.dev/)
for client-side state, styled with [Tailwind CSS](https://tailwindcss.com/) and
[DaisyUI](https://daisyui.com/).

It is **additive**. The Flet frontend is core and always present; selecting
`htmx` puts a second, HTML-first surface beside it, served by the same
webserver process:

```
                    one webserver process
   ┌────────────────────────────────────────────────┐
   │                                                │
   │   /            htmx pages (Jinja2 templates)   │
   │   /dashboard   Flet Overseer dashboard         │
   │   /overseer    server-rendered Overseer page   │
   │   /api/v1/...  FastAPI routes                  │
   │   /static/...  fingerprinted assets            │
   │   /health      component health                │
   │                                                │
   └────────────────────────────────────────────────┘
```

Use the Flet dashboard for operator surfaces and internal tooling; use the
web frontend for anything public-facing, content-heavy, or SEO-relevant. Both
call the same services, so business logic is written once.

## Getting it

On a new project:

```bash
aegis init my-app --components htmx
```

On an existing project:

```bash
aegis add htmx
```

Either way you get a styled landing page at `/`, the Overseer dashboard
untouched at `/dashboard`, and a `web_frontend` entry in `/health`. Removal is
symmetric: `aegis remove htmx` deletes the component tree and regenerates the
shared files that referenced it.

For the first server-rendered Overseer page, include basic auth:

```bash
aegis init my-app --components htmx --services 'auth[basic]'
```

Open `/overseer/login` to sign in. The form uses the shared auth and form
macros and delegates to the existing auth endpoint. A successful sign-in
opens the protected `/overseer` page, which is the starting point for the
server-rendered dashboard.

Basic auth has no email verification step. New registrations are ready
immediately and the registration form redirects to `/overseer`. Email based
password reset is also absent from basic auth because this configuration has
no mail delivery; signed-in password changes remain available.

The shared `feedback`, `form`, `layout`, and `table` macro files were compared
with aegis-pulse and aegis-steward before adding this page. Pulse's shared
`feedback`, `form`, and `table` macros already match the template. The generic
updates brought in from those projects are the dialog behavior, stable search
field ID, and empty-state marker. Steward's account, bill, matter, import,
register, and chat macros depend on its own routes and data, so they remain
in that application.

## What ships

```
app/components/web_frontend/
├── main.py                  # router wiring
├── rendering.py             # Jinja2 env, render() (page or fragment), with_toast()
├── assets.py                # static() helper, CachedStaticFiles
├── filters.py               # money / short_date / pct
├── build.py                 # asset fingerprinting -> static/dist/manifest.json
├── build_watch.py           # dev watcher: re-fingerprint on change
├── routes/
│   ├── pages.py             # page handlers (the landing, auth pages)
│   └── partials/            # fragment-only routes
├── templates/
│   ├── base.html            # document skeleton every page extends
│   ├── layouts/             # page.html and fragment.html, picked by render()
│   ├── pages/               # one template per page
│   └── components/          # macros, feedback macros, landing sections
└── static/
    ├── input.css            # Tailwind entry
    ├── css/app.css          # hand-authored styles
    └── js/app.js            # toasts and htmx error hooks

package.json                 # Tailwind + DaisyUI + Biome (devDependencies only)
tailwind.config.js           # theme + the single rebrand point
```

Plus gated tests (`tests/components/test_web_frontend.py` and the web test
kit under `tests/web/`), Makefile
targets (`build-static`, `lint-frontend`, `format-frontend`), a Docker
`css-build` stage, and two dev-only compose services for hot CSS rebuild.

## First custom page

1. Add a template:

    ```html
    <!-- app/components/web_frontend/templates/pages/about.html -->
    {% extends "base.html" %}
    {% block title %}About - {{ project_name }}{% endblock %}
    {% block content %}
    <section class="py-10">
      <h1 class="text-2xl font-semibold text-white">About</h1>
    </section>
    {% endblock %}
    ```

2. Add a route in `app/components/web_frontend/routes/pages.py`:

    ```python
    @router.get("/about", response_class=HTMLResponse, include_in_schema=False)
    async def about(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="pages/about.html")
    ```

That is the whole loop. In dev no build step is required: `static()` falls
back to unhashed asset paths and pages render immediately. Run
`make build-static` when you want the fingerprinted, long-cacheable variant.

## The rest of these docs

- [Templates and rendering](templates-and-partials.md): the base layout,
  the htmx conventions, and two rules that are load-bearing.
- [Styling and theming](styling.md): the DaisyUI theme and the one place
  brand colors live.
- [Live updates](live-updates.md): snapshots, SSE, and shared health sampling.
- [Asset pipeline](asset-pipeline.md): fingerprinting, the manifest, cache
  policy, and the dev watcher loop.
- [Auth pages](auth-pages.md): what you get when the project also selects
  the auth service.
