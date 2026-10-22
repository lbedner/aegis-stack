/* Appearance: theme (voice, shape, type) x mode (color palette).
   The page says which themes exist and which one it opens with, on this
   script's own tag (appearance_head in components/macros/layout.html):
   data-themes, data-theme, and data-fixed when the layout owns its theme
   (a public site's) and only the mode is the viewer's. */
(() => {
  const root = document.documentElement;
  const tag = document.currentScript?.dataset ?? {};
  const fixed = 'fixed' in tag;
  const choices = {
    theme: (tag.themes || 'aegis').split(' '),
    mode: ['dark', 'light', 'system'],
    sidebar: ['wide', 'rail'],
  };
  const state = { theme: tag.theme || choices.theme[0], mode: 'dark', sidebar: 'wide' };
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  try {
    const legacy = localStorage.getItem('theme');
    if (legacy === 'aegis-light') {
      state.mode = 'light';
      localStorage.setItem('theme', 'aegis');
      localStorage.setItem('mode', 'light');
    } else {
      if (!fixed && choices.theme.includes(legacy)) state.theme = legacy;
      const storedMode = localStorage.getItem('mode');
      if (choices.mode.includes(storedMode)) state.mode = storedMode;
    }
    const storedSidebar = localStorage.getItem('overseer_sidebar');
    if (choices.sidebar.includes(storedSidebar)) state.sidebar = storedSidebar;
  } catch (_) { /* Storage is optional; in-memory choices still work. */ }

  const apply = () => {
    const resolved = state.mode === 'system' ? (media.matches ? 'dark' : 'light') : state.mode;
    root.dataset.theme = `${state.theme}-${resolved}`;
    root.dataset.overseerSidebar = state.sidebar;
    document.dispatchEvent(new CustomEvent('theme-changed', { detail: { ...state } }));
  };
  window.appearance = () => ({ ...state });
  // A choice the server draws the page by (a MenuChoice) names its cookie:
  // kept there, and the page redrawn.
  window.setAppearance = (key, value, cookie) => {
    if (cookie) {
      document.cookie = `${cookie}=${encodeURIComponent(value)}; path=/; max-age=31536000; samesite=lax`;
      location.reload();
      return;
    }
    if (!choices[key]?.includes(value) || (fixed && key === 'theme')) return;
    state[key] = value;
    try { localStorage.setItem(key === 'sidebar' ? 'overseer_sidebar' : key, value); } catch (_) { /* Session only. */ }
    apply();
  };
  media.addEventListener('change', () => { if (state.mode === 'system') apply(); });
  apply();
})();
