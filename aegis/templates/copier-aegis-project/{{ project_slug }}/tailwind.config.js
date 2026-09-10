/** @type {import('tailwindcss').Config} */
// Tailwind + DaisyUI config for the htmx web frontend.
//
// The CSS is compiled ahead of time, never by a runtime CDN JIT: identical
// visual result, zero runtime compile cost, and classes the `content`
// scanner cannot see fail loudly in dev instead of silently in prod. If you
// put Tailwind classes anywhere outside the globs below (a Python string, a
// new template directory), add that path here or they will not be emitted.
//
// Colors are tokens: each aegis-* name reads a CSS variable that the theme
// blocks in static/input.css define per [data-theme]. Change a theme there,
// never here. The DaisyUI themes below mirror the same values in hex so
// DaisyUI's own component classes match.
const token = (name) => `rgb(var(--aegis-${name}) / <alpha-value>)`;

module.exports = {
  content: [
    "./app/components/web_frontend/templates/**/*.html",
    "./app/components/web_frontend/static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        aegis: {
          bg: token("bg"),
          card: token("card"),
          border: token("border"),
          text: token("text"),
          muted: token("muted"),
          teal: token("teal"),
          amber: token("amber"),
          error: token("error"),
          scrim: token("scrim"),
        },
      },
      fontSize: {
        xxs: ["10px", "14px"],
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      {
        aegis: {
          primary: "#17CCBF",
          secondary: "#3B82F6",
          accent: "#F59E0B",
          neutral: "#111418",
          "base-100": "#090B0D",
          "base-200": "#0E1014",
          "base-300": "#111418",
          "base-content": "#EEF1F4",
          info: "#06B6D4",
          success: "#17CCBF",
          warning: "#F59E0B",
          error: "#EF4444",
        },
      },
      {
        "aegis-light": {
          primary: "#0D9488",
          secondary: "#2563EB",
          accent: "#D97706",
          neutral: "#FFFFFF",
          "base-100": "#F6F7F9",
          "base-200": "#EEF0F3",
          "base-300": "#FFFFFF",
          "base-content": "#111418",
          info: "#0891B2",
          success: "#0D9488",
          warning: "#D97706",
          error: "#DC2626",
        },
      },
    ],
  },
};
