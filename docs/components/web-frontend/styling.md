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

The stack uses the appearance system from Aegis Steward. Theme controls
voice and shape (`aegis` or `steward`); mode controls the palette (`dark`,
`light`, or the system preference). The four resolved DaisyUI themes are
`aegis-dark`, `aegis-light`, `steward-dark`, and `steward-light`.

`tailwind.config.js` is the single source for palettes, shapes, light-mode
tints, and chart colors. Its `PALETTES`, `SHAPES`, and `TINTS` tables generate
the four themes. Tailwind's `aegis-*` utilities read DaisyUI's active color
variables, so a color is defined once. `static/input.css` supplies shared
components and applies the theme's scale and label style. `static/js/charts.js`
reads the same color variables.

`static/js/theme.js` applies the stored theme and mode before the stylesheet
paints. It exposes `appearance()` and `setAppearance(key, value)` to the
`theme_toggle()` macro in `components/macros/layout.html`, which appears on
navigation and auth pages. System mode follows `prefers-color-scheme`. The
default is `aegis-dark`, set on `<html>` in `base.html`. Existing
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
