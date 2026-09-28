/** @type {import('tailwindcss').Config} */
// Tailwind + DaisyUI config for the htmx web frontend.
//
// The CSS is compiled ahead of time, never by a runtime CDN JIT: identical
// visual result, zero runtime compile cost, and classes the `content`
// scanner cannot see fail loudly in dev instead of silently in prod. If you
// put Tailwind classes anywhere outside the globs below (a Python string, a
// new template directory), add that path here or they will not be emitted.
//
// THEMES: the single rebrand point.
//
// Two axes. A MODE is a color palette (dark, light). A THEME is a voice and
// a shape (aegis: operational, uppercase micro-labels, tight radius;
// steward: personal, sentence case, softer radius, a touch larger). The
// four DaisyUI themes below are generated from those tables, named
// `<theme>-<mode>`, and applied as `<html data-theme>` by static/js/theme.js.
//
// Every `aegis-*` color name reads a DaisyUI variable, so `bg-aegis-card`
// follows whatever theme is on <html> and no value is written twice. Charts
// read the same variables (see charts.js). Change a color or a shape here,
// nowhere else; tests/web/test_theme.py holds the four themes to parity.

const PALETTES = {
  dark: {
    "color-scheme": "dark", // native controls and scrollbars follow
    primary: "#17CCBF", // teal: brand, action, active
    secondary: "#3B82F6",
    accent: "#F59E0B",
    neutral: "#7E8A9A", // muted text and icons
    "base-100": "#111418", // card / surface
    "base-200": "#090B0D", // page background
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
  },
};

const SHAPES = {
  aegis: {
    "--rounded-box": "0.5rem", // cards, menus, dialogs (rounded-lg)
    "--rounded-btn": "0.25rem", // controls, chips, rows (rounded)
    "--rounded-badge": "0.25rem",
    "--aegis-label-case": "uppercase", // micro-labels: ASSETS, 5 GROUPS
    "--aegis-label-tracking": "0.05em",
    "--aegis-scale": "100%", // root font size; every rem follows
  },
  steward: {
    "--rounded-box": "0.75rem",
    "--rounded-btn": "0.5rem",
    "--rounded-badge": "1rem",
    "--aegis-label-case": "none",
    "--aegis-label-tracking": "0",
    "--aegis-scale": "106.25%", // 17px
  },
};

// Where a theme wants a different tint of a mode's palette: steward's
// light mode is warmer and its borders quieter, so it reads as a personal
// product rather than a console.
const TINTS = {
  steward: {
    light: {
      primary: "#0F8A7E",
      "base-200": "#FAF9F7",
      "base-300": "#E8E5E0",
      neutral: "#66707C",
    },
  },
};

const themes = Object.entries(SHAPES).flatMap(([theme, shape]) =>
  Object.entries(PALETTES).map(([mode, palette]) => ({
    [`${theme}-${mode}`]: { ...palette, ...(TINTS[theme]?.[mode] ?? {}), ...shape },
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
          error: daisy("er"),
          scrim: "rgb(0 0 0 / <alpha-value>)",
        },
      },
      borderRadius: {
        DEFAULT: "var(--rounded-btn)",
        lg: "var(--rounded-box)",
      },
      fontSize: {
        xxs: ["0.625rem", "0.875rem"],
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: { themes, logs: false },
};
