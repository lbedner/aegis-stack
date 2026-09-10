/* Theme switch.

   Loaded synchronously in <head>, ahead of the stylesheet, so the stored
   theme is on <html> before the first paint: a light-theme user never sees
   a dark flash. A theme is a block of CSS variables in input.css keyed by
   [data-theme]; switching is one attribute. Charts listen for
   `theme-changed` and repaint from the new tokens. */
(() => {
  const KEY = 'theme';
  const THEMES = ['aegis', 'aegis-light'];
  const root = document.documentElement;

  let stored = null;
  try {
    stored = localStorage.getItem(KEY);
  } catch (_) {
    /* private mode or storage disabled: keep the default */
  }
  if (stored && THEMES.includes(stored)) root.dataset.theme = stored;

  window.toggleTheme = () => {
    const next = root.dataset.theme === THEMES[0] ? THEMES[1] : THEMES[0];
    root.dataset.theme = next;
    try {
      localStorage.setItem(KEY, next);
    } catch (_) {
      /* not persisted; the switch still applies for this page */
    }
    document.dispatchEvent(new CustomEvent('theme-changed', { detail: { theme: next } }));
  };
})();
