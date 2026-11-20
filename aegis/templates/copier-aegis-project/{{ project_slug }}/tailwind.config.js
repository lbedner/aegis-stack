/** @type {import('tailwindcss').Config} */
// Tailwind + DaisyUI config for the htmx web frontend.
//
// The CSS is compiled ahead of time, never by a runtime CDN JIT: identical
// visual result, zero runtime compile cost, and classes the `content`
// scanner cannot see fail loudly in dev instead of silently in prod. If you
// put Tailwind classes anywhere outside the globs below (a Python string, a
// new template directory), add that path here or they will not be emitted.
//
// THEMES: the modes' palettes live in app/core/palette.json; every theme
// (its shape, type and tints) is a file under
// app/components/web_frontend/themes/, read here and by the server. See docs/components/web-frontend/styling.md.
//
// Every `aegis-*` color name reads a DaisyUI variable, so `bg-aegis-card`
// follows whatever theme is on <html> and no value is written twice.
// Charts read the same variables (see charts.js).

// The palette is a JSON file so Overseer (Flet) builds its light and dark
// schemes from the same values (app/components/frontend/theme.py).
const PALETTES = require("./app/core/palette.json");

const fs = require("fs");
const path = require("path");

const THEMES_DIR = path.join(__dirname, "app/components/web_frontend/themes");
const THEMES = fs
  .readdirSync(THEMES_DIR)
  .filter((file) => file.endsWith(".json"))
  .sort()
  .map((file) => ({
    name: path.basename(file, ".json"),
    ...JSON.parse(fs.readFileSync(path.join(THEMES_DIR, file), "utf8")),
  }));

const themes = THEMES.flatMap((theme) =>
  Object.entries(PALETTES).map(([mode, palette]) => ({
    [`${theme.name}-${mode}`]: {
      ...palette,
      ...(theme.tints?.[mode] ?? {}),
      ...theme.shape,
      "--aegis-font-display": theme.type.display,
      "--aegis-font-body": theme.type.body,
    },
  })),
);

// DaisyUI stores each theme color as an oklch triplet in a short variable.
const daisy = (name) => `oklch(var(--${name}) / <alpha-value>)`;

module.exports = {
  content: [
    "./app/components/web_frontend/templates/**/*.html",
    "./app/components/web_frontend/static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        aegis: {
          bg: daisy("b2"),
          card: daisy("b1"),
          border: daisy("b3"),
          text: daisy("bc"),
          muted: daisy("n"),
          teal: daisy("p"),
          amber: daisy("wa"),
          accent: daisy("a"),
          error: daisy("er"),
          scrim: "rgb(0 0 0 / <alpha-value>)",
        },
      },
      borderRadius: {
        DEFAULT: "var(--rounded-btn)",
        lg: "var(--rounded-box)",
      },
      // A theme's type: `font-display` for titles, `font-body` for the rest
      // (the body's default); never a family name in a template.
      fontFamily: {
        display: "var(--aegis-font-display)",
        body: "var(--aegis-font-body)",
      },
      fontSize: {
        xxs: ["0.625rem", "0.875rem"],
      },
      // A voice control's "speaking" equalizer (components/macros/chat.html).
      keyframes: {
        "voice-bar": {
          "0%, 100%": { transform: "scaleY(0.3)" },
          "50%": { transform: "scaleY(1)" },
        },
      },
      animation: {
        "voice-bar": "voice-bar 0.9s ease-in-out infinite",
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: { themes, logs: false },
};
