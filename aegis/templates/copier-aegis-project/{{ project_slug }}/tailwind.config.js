/** @type {import('tailwindcss').Config} */
// Tailwind + DaisyUI config for the htmx web frontend.
//
// The CSS is compiled ahead of time, never by a runtime CDN JIT: identical
// visual result, zero runtime compile cost, and classes the `content`
// scanner cannot see fail loudly in dev instead of silently in prod. If you
// put Tailwind classes anywhere outside the globs below (a Python string, a
// new template directory), add that path here or they will not be emitted.
//
// THEMES: the modes' palettes live here; every theme (its shape, type and
// tints) is a file under app/components/web_frontend/themes/, read here and
// by the server. See docs/components/web-frontend/styling.md.
//
// Every `aegis-*` color name reads a DaisyUI variable, so `bg-aegis-card`
// follows whatever theme is on <html> and no value is written twice.
// Charts read the same variables (see charts.js).

const PALETTES = {
  dark: {
    "color-scheme": "dark", // native controls and scrollbars follow
    primary: "#17CCBF", // teal: brand, action, active
    secondary: "#3B82F6",
    accent: "#F59E0B",
    neutral: "#7E8A9A", // muted text and icons
    "base-100": "#111418", // card / surface
    "base-200": "#000000", // page background: black, the data on lifted surfaces
    "base-300": "#272C36", // borders, dividers
    "base-content": "#EEF1F4",
    info: "#06B6D4",
    success: "#17CCBF",
    warning: "#F59E0B",
    error: "#EF4444",
    "--aegis-chart-1": "#17CCBF",
    "--aegis-chart-2": "#8B5CF6",
    "--aegis-chart-3": "#F59E0B",
    "--aegis-chart-4": "#3B82F6",
    "--aegis-chart-5": "#EC4899",
    "--aegis-chart-6": "#10B981",
    "--aegis-chart-7": "#F97316",
    "--aegis-chart-8": "#06B6D4",
    "--aegis-chart-9": "#84CC16",
  },
  light: {
    "color-scheme": "light",
    primary: "#0D9488",
    secondary: "#2563EB",
    accent: "#D97706",
    neutral: "#5A6473",
    "base-100": "#FFFFFF",
    "base-200": "#F6F7F9",
    "base-300": "#DEE2E8",
    "base-content": "#111418",
    info: "#0891B2",
    success: "#0D9488",
    warning: "#D97706",
    error: "#DC2626",
    "--aegis-chart-1": "#0D9488",
    "--aegis-chart-2": "#7C3AED",
    "--aegis-chart-3": "#D97706",
    "--aegis-chart-4": "#2563EB",
    "--aegis-chart-5": "#DB2777",
    "--aegis-chart-6": "#059669",
    "--aegis-chart-7": "#EA580C",
    "--aegis-chart-8": "#0891B2",
    "--aegis-chart-9": "#65A30D",
  },
};

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
