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

A theme is one block of CSS variables in `static/input.css`, keyed by
`[data-theme]`:

```css
[data-theme="aegis"] {
  color-scheme: dark;
  --aegis-bg: 9 11 13;        /* page background */
  --aegis-card: 17 20 24;     /* card / surface */
  --aegis-border: 39 44 54;
  --aegis-text: 238 241 244;
  --aegis-muted: 126 138 154;
  --aegis-teal: 23 204 191;   /* brand accent */
  --aegis-amber: 245 158 11;
  --aegis-error: 239 68 68;
  --aegis-scrim: 0 0 0;
  --aegis-chart-1: 23 204 191; /* ... a ramp of eight */
}
```

`tailwind.config.js` maps the `aegis-*` color names onto those variables
(`rgb(var(--aegis-bg) / <alpha-value>)`), so the utilities used throughout
the templates (`bg-aegis-card`, `text-aegis-teal`, `border-aegis-border`)
follow whatever theme is on `<html data-theme>`. Values are RGB triplets so
opacity modifiers like `bg-aegis-teal/10` keep working.

Two themes ship, `aegis` (dark) and `aegis-light`. To add one, add a block
with the same token set; a test holds the shipped blocks to parity. To
rebrand, edit the values. The DaisyUI theme list in `tailwind.config.js`
mirrors each theme in hex so DaisyUI's own component classes (`btn`,
`card`, `alert`) match.

`static/js/theme.js` runs synchronously in `<head>`, ahead of the
stylesheet, so a stored choice is applied before first paint; it exposes
`toggleTheme()`, and the `theme_toggle()` macro in
`components/macros/layout.html` is the button. Default is `aegis`, set on
`<html>` in `base.html`.

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
   `color-scheme` lives with each theme block in `input.css`.

## Linting

`make lint-frontend` runs [Biome](https://biomejs.dev/) over
`static/js/` and [djlint](https://djlint.com/) over the templates. Both are
scoped to the web frontend; neither touches the rest of the project. djlint
runs with the Jinja profile and a small, documented ignore list in
`pyproject.toml` (`[tool.djlint]`). `make format-frontend` reflows the JS with
Biome; it is opt-in because reformatting is noisy in diffs.
