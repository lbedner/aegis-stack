/* htmx lifecycle hooks and the toast component.

   Fragments carry no inline scripts, so nothing here re-executes swapped
   <script> tags. Behaviour that needs JS is registered once, on this
   file's load, and keyed off DOM events. */

// The browser's time zone, for the pages that show times of day (the
// meeting calendar): the server reads it from this cookie (viewer_zone()).
document.cookie = 'tz=' + Intl.DateTimeFormat().resolvedOptions().timeZone + '; path=/; max-age=31536000; samesite=lax';

// Toasts. A route sets `HX-Trigger: {"toast": {"text", "tone"}}` (see
// with_toast() in rendering.py); htmx raises a `toast` DOM event; the
// region in base.html pushes it here.
document.addEventListener('alpine:init', () => {
  Alpine.data('toasts', () => ({
    items: [],
    _seq: 0,
    push(detail) {
      // Shown again on top: the top layer stacks by order of showing.
      if (this.$root.showPopover) {
        if (this.$root.matches(':popover-open')) this.$root.hidePopover();
        this.$root.showPopover();
      }
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

// A form in steps (macros/form.html ``wizard``): one step shown at a
// time, Next only once its fields are valid, and any step already reached
// a click away. ``$bytes`` says a size for people, as charts and the
// server do (charts.js, loaded after this file, by the time it is asked);
// ``$files`` says how many files and how big ("" for none), of a list
// picked or (``$tally``) of a count and a size.
function tally(n, bytes) {
  return n ? `${n} file${n === 1 ? '' : 's'} · ${formatValue(bytes, 'bytes')}` : '';
}
document.addEventListener('alpine:init', () => {
  Alpine.magic('bytes', () => (n) => formatValue(n, 'bytes'));
  Alpine.magic('tally', () => tally);
  Alpine.magic('files', () => (files) => tally(files.length, [...files].reduce((t, f) => t + f.size, 0)));
  Alpine.data('wizard', (count) => ({
    step: 0,
    reached: 0,
    count,
    done(i) {
      return i < this.reached && i !== this.step;
    },
    valid() {
      const here = this.$root.querySelector(`[data-wizard-step="${this.step}"]`);
      return [...here.querySelectorAll('input, select, textarea')].every((f) => f.reportValidity());
    },
    go(i) {
      if (i <= this.reached) this.step = i;
    },
    next() {
      if (!this.valid()) return;
      this.step = Math.min(this.step + 1, this.count - 1);
      this.reached = Math.max(this.reached, this.step);
    },
    back() {
      this.step = Math.max(this.step - 1, 0);
    },
    // Enter in a field is Next, not a submit that skips the steps after
    // it (and their checks); on the last step it submits as ever.
    enter(event) {
      if (event.target.tagName !== 'INPUT' || this.step === this.count - 1) return;
      event.preventDefault();
      this.next();
    },
  }));
  // A file picker that keeps what was picked before (macros/form.html
  // ``file_button`` with ``submit=False``): a second pick adds to the
  // first (one file where it takes one), each listed with its size and
  // removable. The input's own files are kept to the list, so the form
  // posts what it shows; a removal says so with a ``change``.
  Alpine.data('filePicker', (multiple) => ({
    files: [],
    keep(files) {
      const kept = new DataTransfer();
      for (const f of files) kept.items.add(f);
      this.$refs.input.files = kept.files;
      this.files = [...kept.files];
    },
    add() {
      const picked = [...this.$refs.input.files];
      const before = multiple ? this.files : [];
      const fresh = picked.filter((f) => !before.some((b) => b.name === f.name && b.size === f.size));
      this.keep([...before, ...fresh]);
    },
    remove(i) {
      this.keep(this.files.filter((_, at) => at !== i));
      this.$refs.input.dispatchEvent(new Event('change', { bubbles: true }));
    },
    get said() {
      return this.$files(this.files) || 'Nothing chosen';
    },
  }));
});

// A dropdown (macros/layout.html) opens below, on the side its macro
// asked for. One that would run off the bottom of the window opens above
// instead, when there is more room there. A button that wrapped to the
// other edge of a phone would open it off the screen, so on opening it
// takes the other side, then slides back whatever still overhangs.
// ``toggle`` does not bubble, so it is caught on the way down.
function placeDropdown(details) {
  const menu = details.lastElementChild;
  menu.style.left = menu.style.right = menu.style.translate = '';
  menu.style.top = menu.style.bottom = menu.style.marginTop = menu.style.marginBottom = '';
  if (!details.open) return;
  const below = menu.getBoundingClientRect();
  const above = details.getBoundingClientRect().top;
  if (below.bottom > window.innerHeight && above > window.innerHeight - below.top) {
    menu.style.top = 'auto';
    menu.style.bottom = '100%';
    menu.style.marginTop = '0';
    menu.style.marginBottom = '0.25rem'; // the macro's ``mt-1``, on the other side
  }
  // The page's width, not innerWidth: a phone zooms out to show a menu
  // that overhangs, which widens innerWidth until it "fits". The gutter
  // is the macro's ``max-w-[calc(100vw-2rem)]``.
  const gutter = 16;
  const width = document.documentElement.clientWidth;
  const overhang = () => {
    const r = menu.getBoundingClientRect();
    if (r.left < gutter) return gutter - r.left;
    if (r.right > width - gutter) return width - gutter - r.right;
    return 0;
  };
  if (!overhang()) return;
  const [side, other] = menu.classList.contains('right-0') ? ['right', 'left'] : ['left', 'right'];
  menu.style[side] = 'auto';
  menu.style[other] = '0';
  const shift = overhang();
  if (shift) menu.style.translate = `${shift}px 0`;
}
document.addEventListener('toggle', (event) => {
  if (event.target.matches?.('details[data-dropdown]')) placeDropdown(event.target);
}, true);
// An open dropdown closes on a click off it, or on one of its entries (so
// a dialog an entry opens is never under it). One listener for them all:
// a table can have a menu a row.
function closesDropdown(details, target) {
  return !details.contains(target) || Boolean(target.closest('[role="menu"] a, [role="menu"] button'));
}
document.addEventListener('click', (event) => {
  document.querySelectorAll('details[data-dropdown][open]').forEach((details) => {
    if (closesDropdown(details, event.target)) details.removeAttribute('open');
  });
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
// its own (``copy_icon``) shows it for a beat; any other says so in a toast.
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

// Tabs within a view (layout.html's ``tabbed``): a tab shows its panel and
// hides the others. The one picked is remembered by the tabs' name, so a
// view that re-reads itself (a meeting while the bot is in) keeps it.
const pickedTabs = {};
function showTab(tabs, key) {
  pickedTabs[tabs.dataset.tabs] = key;
  for (const tab of tabs.querySelectorAll(':scope > [role="tablist"] [data-tab]')) {
    tab.setAttribute('aria-selected', String(tab.dataset.tab === key));
  }
  for (const panel of tabs.querySelectorAll(':scope > [data-tab-panel]')) {
    panel.hidden = panel.dataset.tabPanel !== key;
  }
}
document.addEventListener('click', (event) => {
  const tab = event.target.closest('[data-tab]');
  if (tab) showTab(tab.closest('[data-tabs]'), tab.dataset.tab);
});
function restoreTabs(root) {
  const all = [...(root.matches?.('[data-tabs]') ? [root] : []), ...root.querySelectorAll('[data-tabs]')];
  for (const tabs of all) {
    const picked = pickedTabs[tabs.dataset.tabs];
    if (picked && tabs.querySelector(`:scope > [data-tab-panel="${picked}"]`)) showTab(tabs, picked);
  }
}
// A fold (``<details data-fold="name">``) remembers whether it was opened or
// closed, by name, so a block that re-sends itself (the worker's queues over
// SSE) keeps what was folded. ``toggle`` does not bubble: caught on the way down.
const folds = {};
document.addEventListener('toggle', (event) => {
  const fold = event.target;
  if (fold.matches?.('details[data-fold]')) folds[fold.dataset.fold] = fold.open;
}, true);
function restoreFolds(root) {
  for (const fold of root.querySelectorAll('details[data-fold]')) {
    if (fold.dataset.fold in folds) fold.open = folds[fold.dataset.fold];
  }
}
// The tabs picked and the folds left, back on whatever htmx brings in;
// again the moment new content is in, before the browser paints it: htmx
// fires ``load`` only once the swap settles, a frame later, and a view
// re-reading itself every few seconds would flash its first tab, and shut
// the folds held open, each time.
function restoreView(root) {
  if (!root?.querySelectorAll) return;
  restoreTabs(root);
  restoreFolds(root);
}
document.body.addEventListener('htmx:load', (event) => restoreView(event.detail.elt));
document.body.addEventListener('htmx:afterSwap', () => restoreView(document.body));
// Something in a hidden panel is shown before it is reached: a note's
// line in the transcript, a ``data-scroll-to`` target, a search hit.
function revealTab(target) {
  const panel = target?.closest('[data-tab-panel]');
  if (panel?.hidden) showTab(panel.parentElement, panel.dataset.tabPanel);
}
document.addEventListener('click', (event) => {
  const link = event.target.closest('a[href^="#"]');
  if (link && link.hash.length > 1) revealTab(document.getElementById(link.hash.slice(1)));
});

// Any ``data-scroll-to`` button brings the element its selector names into
// view (a list's first or last row), scrolling only what it must.
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-scroll-to]');
  if (!button) return;
  const target = document.querySelector(button.dataset.scrollTo);
  revealTab(target);
  target?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
});

// The Overseer sidebar is never swapped (a link replaces only what is right
// of it), so it keeps its scroll; its current mark moves here instead, to
// the link whose page holds the address: the longest such link, so the
// home link marks only the home page.
function markCurrent(links, path) {
  const holds = (href) => path === href || path.startsWith(href + '/');
  const best = [...links].filter((link) => holds(link.getAttribute('href')))
    .sort((a, b) => b.getAttribute('href').length - a.getAttribute('href').length)[0];
  for (const link of links) {
    if (link === best) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
}
document.body.addEventListener('htmx:pushedIntoHistory', () => {
  markCurrent(document.querySelectorAll('#overseer-nav a[href]'), window.location.pathname);
  // Overseer > Code swaps only its file: the tree's link is the address.
  markCurrent(document.querySelectorAll('[data-code-tree] a[href]'), window.location.pathname + window.location.search);
});

// Cmd-P (Ctrl-P) on Overseer > Code jumps to a file by name, not print.
document.addEventListener('keydown', (event) => {
  const jump = document.querySelector('[data-code-jump]');
  if (!jump || event.key !== 'p' || !(event.metaKey || event.ctrlKey)) return;
  event.preventDefault();
  jump.select();
});

// A name clicked in an Overseer > Code Python file peeks beside it (the
// ``#code-peek`` popover): its definition and references. The line is the
// clicked line's address (``data-line-prefix`` and its number), the column
// how far into the line's source (its number left out) the name starts.
function sourceColumn(line, token) {
  const walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
  let column = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (token.contains(node)) return column;
    if (!node.parentElement.closest('.linenos')) column += node.length;
  }
  return null;
}
document.addEventListener('click', (event) => {
  const pane = event.target.closest && event.target.closest('[data-code-symbol]');
  const token = pane && event.target.closest('.highlight :is(.n, .nf, .nc, .nn)');
  const prefix = pane && pane.dataset.linePrefix;
  const line = token && token.closest(`[id^="${prefix}"]`);
  if (!line || getSelection().toString()) return;
  const column = sourceColumn(line, token);
  if (column === null) return;
  // The symbol URL names the open file; the click adds where in it.
  const query = new URLSearchParams({ line: line.id.slice(prefix.length), col: column });
  const peek = document.getElementById('code-peek');
  htmx.ajax('GET', `${pane.dataset.codeSymbol}&${query}`, { target: peek, swap: 'innerHTML' }).then(() => {
    Object.assign(peek.style, { position: 'fixed', inset: 'auto', margin: '0' });
    peek.showPopover();
    // Measured once shown: below the name, or above it near the bottom.
    const at = token.getBoundingClientRect();
    const below = at.bottom + 4 + peek.offsetHeight <= window.innerHeight;
    const left = Math.max(8, Math.min(at.left, window.innerWidth - peek.offsetWidth - 8));
    peek.style.top = `${below ? at.bottom + 4 : Math.max(8, at.top - 4 - peek.offsetHeight)}px`;
    peek.style.left = `${left}px`;
  });
});

// Server and network failures never swap (see the htmx-config
// responseHandling rules in base.html); they surface here as one error
// toast instead of a silently unchanged page.
document.body.addEventListener('htmx:responseError', (event) => {
  if (event.detail.elt.dataset.apiDone !== undefined) return; // told below
  // A drawer for an item no longer there (deleted from that very drawer,
  // or a stale link): it closes, and its parameter leaves the address.
  if (event.detail.target?.id === 'drawer-body' && event.detail.xhr.status === 404) {
    document.getElementById('drawer')?.close();
    return;
  }
  toast(`Request failed (${event.detail.xhr.status})`, 'error');
});

// A 422 swaps for the form it re-renders (base.html). One that is not HTML
// (a service's refusal, FastAPI's own validation) would swap its JSON in
// and blank its target: it is the error toast instead.
document.body.addEventListener('htmx:beforeSwap', (event) => {
  const { xhr, elt } = event.detail;
  const type = xhr.getResponseHeader('Content-Type') || '';
  if (xhr.status !== 422 || type.startsWith('text/html')) return;
  event.detail.shouldSwap = false;
  if (elt.dataset.apiDone === undefined) toast(apiDetail(xhr), 'error'); // told below
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
// A swap into #drawer-body (``hx_drawer``) opens the side drawer the same way.
document.body.addEventListener('htmx:afterSwap', (event) => {
  // A live stream's swap (the SSE extension) carries no target.
  const id = event.detail.target?.id;
  if (id === 'dialog-body') {
    const dialog = document.getElementById('dialog');
    if (dialog && !dialog.open) dialog.showModal();
  }
  if (id === 'drawer-body') {
    const drawer = document.getElementById('drawer');
    if (drawer && !drawer.open) drawer.show();
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
    .then(() => {
      if (!drawer.open) drawer.show();
      // Opened at one line (a search hit's ``data-hit``): bring it into view.
      const hit = drawer.querySelector('[data-hit]');
      revealTab(hit);
      hit?.scrollIntoView({ block: 'center' });
    });
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
  const id = event.detail.target?.id;
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

// The progress bar along the top (#page-progress in base.html): on while
// htmx has a request out, while part of the page is still on its way
// (``data-pending``: a section whose data a live stream brings), and from
// a click on a link that loads another page here until that page replaces
// this one. A link htmx took, a new tab, another site, a download or an
// anchor never starts it.
let requestsOut = 0;
let leaving = false;
function syncProgress() {
  const on = leaving || requestsOut > 0 || document.querySelector('[data-pending]') !== null;
  document.getElementById('page-progress')?.classList.toggle('is-loading', on);
}
function navigates(event) {
  const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
  if (event.button !== 0 || modified || event.defaultPrevented) return false;
  const link = event.target.closest && event.target.closest('a[href]');
  if (!link || link.target || link.hasAttribute('download')) return false;
  return link.origin === window.location.origin && !link.getAttribute('href').startsWith('#');
}
document.addEventListener('click', (event) => {
  if (!navigates(event)) return;
  leaving = true;
  syncProgress();
});
// Counted down when the request ends, not on htmx:afterRequest: that fires
// on the element that sent it, and an element a live frame swapped out while
// its request was out (a Restart button in a row the stream re-sends) is no
// longer in the page, so the event never reaches here.
document.body.addEventListener('htmx:beforeRequest', (event) => {
  requestsOut += 1;
  syncProgress();
  event.detail.xhr.addEventListener('loadend', () => {
    requestsOut = Math.max(0, requestsOut - 1);
    syncProgress();
  }, { once: true });
});
// The page's first paint, and every swap after it (a stream's included).
document.body.addEventListener('htmx:load', syncProgress);
// Back to this page from the browser's cache: nothing is loading.
window.addEventListener('pageshow', () => {
  leaving = false;
  syncProgress();
});

// A range strip (``data-range``: the Logs volume): a click on a bar narrows
// its list (``data-range-of``) to the bar's time, and a drag across several
// to all of them, whichever way it ran; "Whole window"
// (``data-clear-range``) lets it go. The page does it: no request.
function spanned(bars, a, b) {
  const [i, j] = [bars.indexOf(a), bars.indexOf(b)].sort((x, y) => x - y);
  return bars.slice(i, j + 1);
}
let drag = null;
// The click that ends a drag is not a click on the bar under it.
let dragged = false;
function rangeBar(event) {
  return event.target.closest && event.target.closest('[data-range] [data-to]');
}
function markDrag(on) {
  const covered = new Set(on ? spanned(drag.bars, drag.first, drag.last) : []);
  drag.bars.forEach((bar) => {
    bar.toggleAttribute('data-selecting', covered.has(bar));
  });
}
document.addEventListener('pointerdown', (event) => {
  const bar = rangeBar(event);
  if (!bar || event.button !== 0) return;
  const bars = [...bar.closest('[data-range]').querySelectorAll('[data-to]')];
  drag = { bars, first: bar, last: bar };
  markDrag(true);
});
document.addEventListener('pointerover', (event) => {
  const bar = drag && rangeBar(event);
  if (!bar || !drag.bars.includes(bar)) return;
  drag.last = bar;
  markDrag(true);
});
document.addEventListener('pointerup', () => {
  if (!drag) return;
  const covered = spanned(drag.bars, drag.first, drag.last);
  const strip = drag.first.closest('[data-range]');
  markDrag(false);
  drag = null;
  if (covered.length < 2) return; // a click: the click handler's
  dragged = true;
  setRange(strip, covered[0].dataset.from, covered[covered.length - 1].dataset.to);
});
document.addEventListener('click', (event) => {
  if (dragged) {
    // The click that ends a drag: the drag already picked the range.
    dragged = false;
    return;
  }
  if (!event.target.closest) return;
  const bar = rangeBar(event);
  if (bar) {
    setRange(bar.closest('[data-range]'), bar.dataset.from, bar.dataset.to);
    return;
  }
  const clear = event.target.closest('[data-clear-range]');
  if (clear) setRange(document.getElementById(clear.dataset.clearRange), null, null);
});
// The range a strip picked (``data-picked-from`` and ``-to``, in ms), or null.
function pickedRange(strip) {
  if (!strip || strip.dataset.pickedFrom === undefined) return null;
  return [Number(strip.dataset.pickedFrom), Number(strip.dataset.pickedTo)];
}
function stripOf(list) {
  return list.id ? document.querySelector(`[data-range-of="${list.id}"]`) : null;
}
// Picks (or, with null, lets go of) a strip's range: its bars marked, its
// list narrowed, the URL kept.
function setRange(strip, from, to) {
  if (!strip) return;
  if (from === null) {
    delete strip.dataset.pickedFrom;
    delete strip.dataset.pickedTo;
  } else {
    strip.dataset.pickedFrom = from;
    strip.dataset.pickedTo = to;
  }
  const range = pickedRange(strip);
  strip.querySelectorAll('[data-to]').forEach((bar) => {
    const middle = Math.floor((Number(bar.dataset.from) + Number(bar.dataset.to)) / 2);
    bar.toggleAttribute('aria-current', range !== null && range[0] <= middle && middle < range[1]);
  });
  document.querySelectorAll(`[data-clear-range="${strip.id}"]`).forEach((button) => {
    button.hidden = range === null;
  });
  const list = document.getElementById(strip.dataset.rangeOf);
  if (!list) return;
  showRows(list, [...list.children]);
  keepFacetsInUrl(list);
  queueScreen();
}

// The bars behind what is on screen: a strip that names a list
// (``data-range-of``, its rows' times in ``data-at``) marks the bars from
// its oldest to its newest visible line, as it scrolls and as lines arrive.
function inView(bars, lo, hi) {
  if (lo === null || hi === null) return [];
  return bars.filter((bar) => Number(bar.dataset.from) <= hi && Number(bar.dataset.to) > lo);
}
// The rows on screen in the lists a strip or a search follows, kept by one
// IntersectionObserver, so nothing measures every row on a scroll or as a
// search shows hundreds again; a hidden row is not on screen.
const onScreen = new Set();
const screenWatch = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) onScreen.add(entry.target);
    else onScreen.delete(entry.target);
  });
  queueScreen();
});
function watchedLists() {
  const ranged = [...document.querySelectorAll('[data-range-of]')].map((strip) => document.getElementById(strip.dataset.rangeOf));
  const searched = [...document.querySelectorAll('input[data-filter]')].map((input) => document.querySelector(input.dataset.filter));
  const faceted = [...document.querySelectorAll('form[data-facets]')].map((form) => document.querySelector(form.dataset.facets));
  return [...new Set([...ranged, ...searched, ...faceted].filter(Boolean))];
}
// Each list is watched once, and then only the rows that arrive (a stream's
// batch) are: nothing re-walks a list that only grows.
const watched = new WeakSet();
const rowsAdded = typeof MutationObserver === 'undefined' ? null : new MutationObserver((records) => {
  records.forEach((record) => {
    const rows = [...record.addedNodes].filter((node) => node.nodeType === 1);
    rows.forEach((row) => {
      screenWatch?.observe(row);
    });
    showRows(record.target, rows);
  });
  queueScreen();
});
function watchLists() {
  watchedLists().forEach((list) => {
    if (watched.has(list)) return;
    watched.add(list);
    for (const row of list.children) screenWatch?.observe(row);
    rowsAdded?.observe(list, { childList: true });
    showRows(list, [...list.children]);
    recount(list);
  });
}
function rowsOnScreen(list) {
  return [...onScreen].filter((row) => list.contains(row));
}
function markInView() {
  document.querySelectorAll('[data-range-of]').forEach((strip) => {
    const list = document.getElementById(strip.dataset.rangeOf);
    const times = list ? rowsOnScreen(list).map((row) => Number(row.dataset.at)).filter(Boolean) : [];
    const span = times.length ? [Math.min(...times), Math.max(...times)] : [null, null];
    const bars = [...strip.querySelectorAll('[data-to]')];
    const seen = new Set(inView(bars, ...span));
    bars.forEach((bar) => {
      bar.toggleAttribute('data-in-view', seen.has(bar));
    });
  });
}
let screenFrame = 0;
function queueScreen() {
  cancelAnimationFrame(screenFrame);
  screenFrame = requestAnimationFrame(() => {
    onScreen.forEach((row) => {
      if (!row.isConnected) onScreen.delete(row);
    });
    markInView();
    highlightOnScreen();
  });
}
// The first paint and every swap: a new list is watched (and searched, its
// box filled from the URL), and what is on screen marked.
document.body.addEventListener('htmx:load', () => {
  watchLists();
  queueScreen();
});

// A search over what is on the page (the ``filter_input`` macro): typing
// narrows its target's rows (``data-filter``) to those holding the text,
// any case, and marks each match; rows that arrive later follow it; the
// text rides in the URL. No request: whatever is there, at once.
// splitMatches is split_matches' twin (app.core.formatting), held to one
// table of cases (tests/test_formatting.py MATCH_CASES).
function splitMatches(text, query) {
  if (!query) return [[text, false]];
  const runs = [];
  const lower = text.toLowerCase();
  const needle = query.toLowerCase();
  let at = 0;
  for (let hit = lower.indexOf(needle); hit !== -1; hit = lower.indexOf(needle, at)) {
    if (hit > at) runs.push([text.slice(at, hit), false]);
    runs.push([text.slice(hit, hit + needle.length), true]);
    at = hit + needle.length;
  }
  if (at < text.length) runs.push([text.slice(at), false]);
  return runs.length ? runs : [[text, false]];
}
// Each row's text, lowercased once: a row's lines do not change.
const rowText = new WeakMap();
function textOf(row) {
  let text = rowText.get(row);
  if (text === undefined) {
    text = row.textContent.toLowerCase();
    rowText.set(row, text);
  }
  return text;
}
// The matches on screen, painted with the CSS Highlight API
// (``::highlight(found)`` in input.css): no element added or removed, and
// only the rows showing, re-painted as they scroll. Without the API the
// rows still filter, unmarked.
function rangesIn(row, query) {
  const ranges = [];
  const walker = document.createTreeWalker(row, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.parentElement.closest('button, svg') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  while (walker.nextNode()) {
    const node = walker.currentNode;
    let at = 0;
    splitMatches(node.data, query).forEach(([run, hit]) => {
      if (hit) {
        const range = new Range();
        range.setStart(node, at);
        range.setEnd(node, at + run.length);
        ranges.push(range);
      }
      at += run.length;
    });
  }
  return ranges;
}
function highlightOnScreen() {
  if (typeof CSS === 'undefined' || !CSS.highlights) return;
  const ranges = [];
  document.querySelectorAll('input[data-filter]').forEach((input) => {
    const query = input.value.trim();
    const list = document.querySelector(input.dataset.filter);
    if (query && list) rowsOnScreen(list).forEach((row) => {
        ranges.push(...rangesIn(row, query));
      });
  });
  if (ranges.length) CSS.highlights.set('found', new Highlight(...ranges));
  else CSS.highlights.delete('found');
}
let urlTimer = 0;
function keepInUrl(input, query) {
  clearTimeout(urlTimer);
  urlTimer = setTimeout(() => {
    const url = new URL(window.location.href);
    if (query) url.searchParams.set(input.name, query);
    else url.searchParams.delete(input.name);
    window.history.replaceState(window.history.state, '', url);
  }, 300);
}
// The search box over ``list``, if it has one.
function searchOf(list) {
  return [...document.querySelectorAll('input[data-filter]')].find((input) => list.matches(input.dataset.filter));
}
// ``rows`` shown or hidden by everything over ``list``: its search's text,
// its filters (``data-facets``) and its strip's picked range, touching only
// those that change. A row with no time is outside any range.
function showRows(list, rows) {
  const input = searchOf(list);
  const needle = input ? input.value.trim().toLowerCase() : '';
  const groups = groupsOf(facetsOf(list));
  const range = pickedRange(stripOf(list));
  rows.forEach((row) => {
    const at = Number(row.dataset.at);
    const hide = (Boolean(needle) && !textOf(row).includes(needle))
      || !facetsKeep(row, groups)
      || (range !== null && !(at >= range[0] && at < range[1]));
    if (row.hidden !== hide) row.hidden = hide;
  });
}
// Typing faster than a frame applies once, with the latest text.
let filterFrame = 0;
document.addEventListener('input', (event) => {
  if (!event.target.matches || !event.target.matches('[data-filter]')) return;
  const input = event.target;
  cancelAnimationFrame(filterFrame);
  filterFrame = requestAnimationFrame(() => {
    const list = document.querySelector(input.dataset.filter);
    if (!list) return;
    showRows(list, [...list.children]);
    keepInUrl(input, input.value.trim());
    queueScreen();
  });
});

// The filters over a list (``data-facets``: a form naming it, the Logs
// page's): only the window asks the server; everything else narrows the
// rows already here, new ones included (``showRows``), with no request.
// Each checklist (``data-checklist``) keeps a row any of its ticks match
// (``data-facet-<name>`` on the row: a level, a service, a container; a
// row with several, a voice's models, holds them space-separated); an
// empty one keeps every row; every one must keep it. ``kept`` is that rule
// on a row's values (``of(name)``).
function kept(groups, of) {
  return groups.every((ticks) => ticks.some(([name, value]) => (of(name) || '').split(' ').includes(value)));
}
function facetsOf(list) {
  return [...document.querySelectorAll('form[data-facets]')].find((form) => list.matches(form.dataset.facets));
}
function groupsOf(form) {
  if (!form) return [];
  return [...form.querySelectorAll('[data-checklist]')]
    .map((checklist) => [...checklist.querySelectorAll('input[type=checkbox]:checked')].map((box) => [box.name, box.value]))
    .filter((ticks) => ticks.length);
}
function facetsKeep(row, groups) {
  return kept(groups, (name) => row.getAttribute(`data-facet-${name}`));
}
// ``ui_logs._volume``'s twin: each bar's rows by tone (warn, error, the
// rest); a row before the first bar is left out, one after the last lands
// in it.
function volumeOf(bars, rows) {
  const counts = bars.map(() => ({ error: 0, warn: 0, other: 0, total: 0 }));
  if (!bars.length) return counts;
  rows.forEach(({ at, tone }) => {
    if (!(at >= bars[0].from)) return;
    const found = bars.findIndex((bar) => at < bar.to);
    const count = counts[found === -1 ? bars.length - 1 : found];
    count[tone === 'error' || tone === 'warn' ? tone : 'other'] += 1;
    count.total += 1;
  });
  return counts;
}
// A list's strip recounted over the rows its filters keep (not its search
// or range, as the server counts), each tone's height against the tallest
// bar.
function recount(list) {
  const strip = stripOf(list);
  if (!strip) return;
  const groups = groupsOf(facetsOf(list));
  const bars = [...strip.querySelectorAll('[data-to]')];
  const rows = [...list.children]
    .filter((row) => facetsKeep(row, groups))
    .map((row) => ({ at: Number(row.dataset.at), tone: row.dataset.tone || '' }));
  const counts = volumeOf(bars.map((bar) => ({ from: Number(bar.dataset.from), to: Number(bar.dataset.to) })), rows);
  const peak = Math.max(1, ...counts.map((count) => count.total));
  bars.forEach((bar, i) => {
    bar.querySelectorAll('[data-tone]').forEach((span) => {
      const n = counts[i][span.dataset.tone === 'muted' ? 'other' : span.dataset.tone];
      span.dataset.count = String(n);
      span.style.height = `${Math.round((n / peak) * 1000) / 10}%`;
    });
    bar.title = `${bar.dataset.label} · ${counts[i].total} lines`;
  });
}
// The order flips the rows in place, the end new ones join at, and the end
// the scroller keeps in view.
function reorder(list, order) {
  const newest = order === 'desc';
  if ((list.getAttribute('hx-swap') === 'afterbegin') === newest) return;
  list.append(...[...list.children].reverse());
  list.setAttribute('hx-swap', newest ? 'afterbegin' : 'beforeend');
  const scroller = list.closest('[data-scroll]');
  scroller?.classList.toggle('flex-col', newest);
  scroller?.classList.toggle('flex-col-reverse', !newest);
}
// The filters ride in the URL, as the search does, so a reload or a shared
// link opens the page as it was left.
function keepFacetsInUrl(list) {
  const url = new URL(window.location.href);
  const form = facetsOf(list);
  if (form) {
    const fields = [...form.elements].filter((el) => el.name && el.name !== 'window' && !el.matches('[data-filter]'));
    new Set(fields.map((el) => el.name)).forEach((name) => {
      url.searchParams.delete(name);
    });
    fields.forEach((el) => {
      if (el.type === 'checkbox' ? el.checked : el.value) url.searchParams.append(el.name, el.value);
    });
  }
  const range = pickedRange(stripOf(list));
  ['from', 'to'].forEach((key, i) => {
    if (range) url.searchParams.set(key, String(range[i]));
    else url.searchParams.delete(key);
  });
  window.history.replaceState(window.history.state, '', url);
}
document.addEventListener('change', (event) => {
  const form = event.target.closest && event.target.closest('form[data-facets]');
  if (!form || event.target.name === 'window' || event.target.matches('[data-filter]')) return;
  const list = document.querySelector(form.dataset.facets);
  if (!list) return;
  if (event.target.name === 'order') reorder(list, event.target.value);
  showRows(list, [...list.children]);
  recount(list);
  keepFacetsInUrl(list);
  queueScreen();
});

// The dismissal rules, for the node tests (tests/web/test_app_js.py).
// The map (_overview_map.html): hovering a node keeps it, its lines and the
// nodes they join lit, and dims the rest, so "who uses the Database" reads
// at a glance; leaving it (the window too) lets it go. Kept on the stream's wrapper
// (#overview-stack, outside what each frame swaps), so a live frame keeps it.
// A route's dry path arrives as ``data-lit`` there (``?lit=``): its parts
// stay lit, and the lines between two of them, while no node is hovered.
function mapFocus(lines, key) {
  const lit = new Set([key]);
  lines.forEach(({ from, to }) => {
    if (from === key) lit.add(to);
    if (to === key) lit.add(from);
  });
  return lit;
}
function pathFocus(keys) {
  return new Set(keys.split(','));
}
function applyMapFocus(root) {
  const map = root && root.querySelector('[data-map]');
  if (!map) return;
  const key = root.dataset.hover;
  const lines = [...map.querySelectorAll('path[data-link]')];
  const path = !key && root.dataset.lit ? pathFocus(root.dataset.lit) : null;
  const lit = key ? mapFocus(lines.map((line) => line.dataset), key) : path || new Set();
  lines.forEach((line) => {
    const { from, to } = line.dataset;
    const kept = path ? lit.has(from) && lit.has(to) : from === key || to === key;
    line.toggleAttribute('data-dim', Boolean(key || path) && !kept);
  });
  map.querySelectorAll('[data-node]').forEach((node) => {
    node.toggleAttribute('data-dim', Boolean(key || path) && !lit.has(node.dataset.node));
  });
}
document.addEventListener('mouseover', (event) => {
  const root = document.getElementById('overview-stack');
  if (!root) return;
  const node = event.target.closest && event.target.closest('[data-map] [data-node]');
  const key = node ? node.dataset.node : '';
  if ((root.dataset.hover || '') === key) return;
  if (key) root.dataset.hover = key;
  else delete root.dataset.hover;
  applyMapFocus(root);
});
// Out of the window straight from a node: no mouseover follows to clear it.
document.addEventListener('mouseout', (event) => {
  const root = document.getElementById('overview-stack');
  if (event.relatedTarget || !root || !root.dataset.hover) return;
  delete root.dataset.hover;
  applyMapFocus(root);
});
document.body.addEventListener('htmx:load', () => {
  applyMapFocus(document.getElementById('overview-stack'));
});

if (typeof module !== 'undefined') module.exports = { revealTab, placeDropdown, closesDropdown, outsideClick, dismiss, navigates, markCurrent, spanned, inView, splitMatches, mapFocus, pathFocus, sourceColumn, kept, volumeOf };
