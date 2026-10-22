# Styling and Theming

## Precompiled, never CDN

Tailwind is compiled ahead of time into `static/dist/app.css`. There is no
runtime JIT and no CDN script tag. The visual result is identical; the
difference is that classes Tailwind cannot see fail loudly in development
instead of silently in production, and pages ship one minified stylesheet
instead of a compiler.

```bash
npm install          # once; pulls Tailwind, DaisyUI, Biome (devDependencies only)
make build-static    # compile + fingerprint
```

In development you rarely need either: pages render without a build because
asset resolution falls back to source paths (see
[Asset pipeline](asset-pipeline.md)), and `make serve` runs a watcher that
rebuilds CSS on template changes.

!!! warning "Tailwind only emits classes it can see"
    `tailwind.config.js` scans `app/components/web_frontend/templates/**/*.html`
    and `static/js/**/*.js`. A Tailwind class anywhere else (a Python string,
    a new template directory) will not be in the compiled CSS. If you add a
    template location, add its glob to `content` in `tailwind.config.js`.

## The single rebrand point

Two axes cross. A theme is a shape and a type; a mode is a palette
(`dark`, `light`, or the system preference). Every theme is one file under
`app/components/web_frontend/themes/`, named for it (`aegis.json`,
`steward.json`; a project adds its own beside them, and commits it), and
`tailwind.config.js` reads the folder to generate one DaisyUI theme per
theme and mode, named `<theme>-<mode>`. The modes' palettes and the chart
colors live in the config; a theme file holds its shape (radius, label
case, scale), its type (a display face, a body face, and the stylesheet
that loads them, if any) and any tint it gives a mode's palette (steward's
light mode is warmer). A theme's `fonts` may be a local stylesheet for
self-hosted faces; a Google Fonts URL sends every visitor's address to
Google.

Tailwind's `aegis-*` utilities read DaisyUI's active color variables, so a
color is defined once. `font-display` and `font-body` read the theme's
faces; the body wears `font-body` by default. `static/input.css` supplies
shared components and applies the theme's scale and label style.
`static/js/charts.js` reads the same color variables.

The server reads the same files (`web_frontend/themes.py`). `WEB_THEME`
names the theme the Overseer opens with, and a name no file has fails at
boot, listing the ones that exist. A layout puts `appearance_head(theme)`
(`components/macros/layout.html`) in its `<head>`: the theme script, told
which themes exist and which this page opens with, then the theme's type,
then the stylesheet. A public layout passes `fixed=true` to wear its own
theme whatever the viewer chose elsewhere; the viewer still picks the mode.

`static/js/theme.js` applies the stored theme and mode before the stylesheet
paints. It exposes `appearance()` and `setAppearance(key, value)` to the
`theme_toggle()` macro, which offers every theme and appears on navigation
and auth pages. System mode follows `prefers-color-scheme`. Existing
`aegis-light` preferences are migrated to theme `aegis`, mode `light`.

Nothing else names a color. A test fails on any hex literal, and on any
theme-blind class such as `text-white` or `bg-black`, in templates or
static JS; use `text-aegis-text` and `bg-aegis-scrim` instead.

## The layers

Three places styling can live, in order of preference:

1. **Utility classes in templates.** The default. Most of the shipped markup
   is plain Tailwind utilities.
2. **`static/input.css`, `@layer components`.** For a pattern that repeats
   across templates when a Jinja macro would be overkill:

    ```css
    @layer components {
      .card-surface {
        @apply bg-aegis-card border border-aegis-border rounded-lg;
      }
    }
    ```

    Utilities are emitted after this layer, so a call site can still override
    a component class.

3. **`static/css/app.css`.** Hand-authored CSS that is not Tailwind at all.
   It ships with `[x-cloak]{display:none}` (hides elements until Alpine
   initializes them, preventing a flash of unstyled content on htmx swaps)
   and the native `accent-color`, read from the theme's token.
   `color-scheme` lives with each generated DaisyUI theme in `tailwind.config.js`.

## Linting

`make lint-frontend` runs [Biome](https://biomejs.dev/) over
`static/js/` and [djlint](https://djlint.com/) over the templates. Both are
scoped to the web frontend; neither touches the rest of the project. djlint
runs with the Jinja profile and a small, documented ignore list in
`pyproject.toml` (`[tool.djlint]`). `make format-frontend` reflows the JS with
Biome; it is opt-in because reformatting is noisy in diffs.
