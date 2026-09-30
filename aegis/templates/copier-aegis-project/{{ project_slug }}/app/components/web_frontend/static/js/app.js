/* htmx lifecycle hooks and the toast component.

   Fragments carry no inline scripts, so nothing here re-executes swapped
   <script> tags. Behaviour that needs JS is registered once, on this
   file's load, and keyed off DOM events. */

// Toasts. A route sets `HX-Trigger: {"toast": {"text", "tone"}}` (see
// with_toast() in rendering.py); htmx raises a `toast` DOM event; the
// region in base.html pushes it here.
document.addEventListener('alpine:init', () => {
  Alpine.data('toasts', () => ({
    items: [],
    _seq: 0,
    push(detail) {
      const id = ++this._seq;
      const tone = detail.tone || 'ok';
      this.items.push({ id, text: detail.text, tone });
      // Errors linger; confirmations get out of the way.
      setTimeout(() => this.dismiss(id), tone === 'error' ? 8000 : 4000);
    },
    dismiss(id) {
      this.items = this.items.filter((item) => item.id !== id);
    },
  }));
});

function toast(text, tone) {
  window.dispatchEvent(new CustomEvent('toast', { detail: { text, tone } }));
}

// The one copier: any ``data-copy`` button puts its text on the clipboard.
// navigator.clipboard exists only in a secure context, which a stack served
// over plain http to anything but localhost is not, so the old execCommand
// path keeps every copy button working on a LAN address.
function copyText(text) {
  if (navigator.clipboard) return navigator.clipboard.writeText(text);
  const box = document.createElement('textarea');
  box.value = text;
  box.setAttribute('readonly', '');
  box.style.cssText = 'position:fixed;top:-1000px;opacity:0';
  document.body.appendChild(box);
  box.select();
  const ok = document.execCommand('copy');
  box.remove();
  return ok ? Promise.resolve() : Promise.reject(new Error('copy refused'));
}
// The clipboard says nothing back, so the button does: one with a tick of
// its own (the chat's) shows it for a beat; any other says so in a toast.
const COPIED_MS = 1200;
function showCopied(button, on) {
  button.querySelector('[data-copy-idle]')?.classList.toggle('hidden', on);
  button.querySelector('[data-copy-done]')?.classList.toggle('hidden', !on);
  if (on) button.dataset.copied = 'true';
  else delete button.dataset.copied;
}
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-copy]');
  if (!button || !button.dataset.copy) return;
  const ticks = button.querySelector('[data-copy-done]');
  copyText(button.dataset.copy).then(
    () => {
      if (!ticks) return toast('Copied to clipboard', 'ok');
      showCopied(button, true);
      clearTimeout(button._settle);
      button._settle = setTimeout(() => showCopied(button, false), COPIED_MS);
    },
    () => toast('Could not copy - select the text instead', 'error'),
  );
});

// Server and network failures never swap (see the htmx-config
// responseHandling rules in base.html); they surface here as one error
// toast instead of a silently unchanged page.
document.body.addEventListener('htmx:responseError', (event) => {
  if (event.detail.elt.dataset.apiDone !== undefined) return; // told below
  toast(`Request failed (${event.detail.xhr.status})`, 'error');
});

// A button that calls the JSON API directly (the Overseer's Authentication
// actions) says what it did in `data-api-done`. The API answers with JSON,
// not HTML, so nothing swaps: on success the dialog closes, the toast
// shows, and the page's main area is re-requested to show the change; on
// failure the API's own `detail` is the toast.
document.body.addEventListener('htmx:afterRequest', (event) => {
  const done = event.detail.elt.dataset.apiDone;
  if (done === undefined) return;
  if (!event.detail.successful) {
    toast(apiDetail(event.detail.xhr), 'error');
    return;
  }
  document.body.dispatchEvent(new Event('dialog:close'));
  toast(done, 'ok');
  // The whole URL: a page's state (a filter, the open folder) lives in
  // its query string.
  htmx.ajax('GET', window.location.pathname + window.location.search, {
    target: '#overseer-main', select: '#overseer-main', swap: 'outerHTML',
  });
});

function apiDetail(xhr) {
  try {
    const detail = JSON.parse(xhr.responseText).detail;
    if (typeof detail === 'string') return detail;
  } catch (_) { /* not JSON */ }
  return `Request failed (${xhr.status})`;
}
document.body.addEventListener('htmx:sendError', () => {
  toast('Network error. Check the connection and try again.', 'error');
});

// The one modal. Any swap into #dialog-body opens the native <dialog>;
// closing it clears the body (see the dialog macro in macros/layout.html).
document.body.addEventListener('htmx:afterSwap', (event) => {
  if (event.detail.target.id === 'dialog-body') {
    const dialog = document.getElementById('dialog');
    if (dialog && !dialog.open) dialog.showModal();
  }
});
// The one drawer. A list renders a ``drawer_sync`` marker naming what is
// open, so the address bar is the state: a row click navigates the list
// with ``?document=12``, a reload or a shared link opens the same item,
// and a list without one (after a delete, say) closes it. Closing drops
// the parameter from the address without a request.
function syncDrawer(root) {
  const marker = root.querySelector && root.querySelector('[data-drawer-sync]');
  const drawer = document.getElementById('drawer');
  if (!drawer) return;
  if (!marker) {
    // Another section took the page: its item is not this one.
    const page = root.id === 'overseer-main' || (root.querySelector && root.querySelector('#overseer-main'));
    if (page && drawer.open) drawer.close();
    return;
  }
  drawer.dataset.param = marker.dataset.drawerParam;
  const url = marker.dataset.drawerUrl;
  if (!url) {
    if (drawer.open) drawer.close();
    return;
  }
  htmx.ajax('GET', url, { target: '#drawer-body', swap: 'innerHTML' })
    .then(() => { if (!drawer.open) drawer.show(); });
}
document.body.addEventListener('htmx:load', (event) => syncDrawer(event.detail.elt));

// Light dismiss for the drawer and the modal. A click outside or Escape
// closes the panel; a click on a row that opens another item switches to
// it; typed-but-unsaved work holds the panel open with a toast. The X and
// Cancel still close on purpose. A form inside a panel is dirty once
// typed in, and clean again when it saves or the panel reloads.
function outsideClick(panel, target) {
  if (!panel.open || panel.contains(target)) return 'ignore';
  if (target.closest('dialog[open]')) return 'ignore'; // the modal, over the drawer
  if (panel.dataset.dirty) return 'hold';
  const param = panel.dataset.param;
  const opensItem = `[href*="${param}="], [hx-get*="${param}="]`; // a row, "New post"
  return param && target.closest(opensItem) ? 'ignore' : 'close';
}
function dismiss(panel) {
  if (panel.dataset.dirty) {
    toast('Unsaved changes: save or close', 'warn');
    return false;
  }
  panel.close();
  return true;
}
function markClean(panel) {
  if (panel) delete panel.dataset.dirty;
}
document.addEventListener('click', (event) => {
  const drawer = document.getElementById('drawer');
  const modal = document.getElementById('dialog');
  if (event.target.closest('[data-drawer-close]')) {
    markClean(drawer);
    drawer.close();
    return;
  }
  if (modal && modal.open) {
    if (event.target === modal) dismiss(modal); // the backdrop
    return;
  }
  if (!drawer) return;
  const verdict = outsideClick(drawer, event.target);
  if (verdict === 'close') drawer.close();
  if (verdict === 'hold') {
    event.preventDefault();
    event.stopPropagation();
    dismiss(drawer);
  }
}, true);
document.addEventListener('keydown', (event) => {
  const drawer = document.getElementById('drawer');
  const modal = document.getElementById('dialog');
  if (event.key !== 'Escape' || (modal && modal.open)) return; // its cancel, below
  if (drawer && drawer.open) dismiss(drawer);
});
// A modal's Escape arrives as ``cancel``; unsaved work cancels the cancel.
document.addEventListener('cancel', (event) => {
  if (event.target.id !== 'dialog' || !event.target.dataset.dirty) return;
  event.preventDefault();
  dismiss(event.target);
}, true);
document.addEventListener('input', (event) => {
  const panel = event.target.closest && event.target.closest('#drawer, #dialog');
  if (panel && event.target.closest('form')) panel.dataset.dirty = '1';
});
document.body.addEventListener('htmx:afterRequest', (event) => {
  const form = event.detail.elt.closest && event.detail.elt.closest('form');
  if (!event.detail.successful || !form) return;
  let said = {};
  try { said = JSON.parse(event.detail.xhr.getResponseHeader('HX-Trigger') || '{}'); } catch { said = {}; }
  if (said.toast && said.toast.tone === 'error') return; // refused: still unsaved
  markClean(form.closest('#drawer, #dialog'));
});
document.body.addEventListener('htmx:afterSwap', (event) => {
  const id = event.detail.target.id;
  if (id === 'drawer-body' || id === 'dialog-body') markClean(event.detail.target.closest('dialog'));
});
// ``close`` does not bubble; the capture phase still sees it.
document.addEventListener('close', (event) => {
  const drawer = event.target;
  if (drawer.id === 'dialog') markClean(drawer);
  if (drawer.id !== 'drawer') return;
  markClean(drawer);
  drawer.querySelector('#drawer-body').innerHTML = '';
  const url = new URL(window.location.href);
  if (drawer.dataset.param && url.searchParams.has(drawer.dataset.param)) {
    url.searchParams.delete(drawer.dataset.param);
    history.replaceState(history.state, '', url);
  }
}, true);
// Sent as HX-Trigger-After-Settle (rendering.close_dialog), so it lands
// after the response's own swap has finished with #dialog-body.
document.body.addEventListener('dialog:close', () => {
  const dialog = document.getElementById('dialog');
  if (dialog && dialog.open) dialog.close();
});

// The dismissal rules, for the node tests (tests/web/test_app_js.py).
if (typeof module !== 'undefined') module.exports = { outsideClick, dismiss };
