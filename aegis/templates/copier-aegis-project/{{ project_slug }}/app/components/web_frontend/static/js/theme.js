/* Steward appearance: theme (voice and shape) x mode (color palette). */
(() => {
  const root = document.documentElement;
  const choices = { theme: ['aegis', 'steward'], mode: ['dark', 'light', 'system'], sidebar: ['wide', 'rail'] };
  const state = { theme: 'aegis', mode: 'dark', sidebar: 'wide' };
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  try {
    const legacy = localStorage.getItem('theme');
    if (legacy === 'aegis-light') {
      state.mode = 'light';
      localStorage.setItem('theme', 'aegis');
      localStorage.setItem('mode', 'light');
    } else {
      if (choices.theme.includes(legacy)) state.theme = legacy;
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
    if (!choices[key]?.includes(value)) return;
    state[key] = value;
    try { localStorage.setItem(key === 'sidebar' ? 'overseer_sidebar' : key, value); } catch (_) { /* Session only. */ }
    apply();
  };
  media.addEventListener('change', () => { if (state.mode === 'system') apply(); });
  apply();
})();
