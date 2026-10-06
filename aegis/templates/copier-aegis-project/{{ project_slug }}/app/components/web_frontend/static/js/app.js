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

// Any ``data-scroll-to`` button brings the element its selector names into
// view (a list's first or last row), scrolling only what it must.
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-scroll-to]');
  if (!button) return;
  document.querySelector(button.dataset.scrollTo)
    ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
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
// to it (its own link), and a drag across several narrows to all of them:
// the first bar's request, every filter it carries, with the last bar's
// end (``data-to``), whichever way the drag ran.
function rangeUrl(href, to) {
  const url = new URL(href, 'http://local');
  url.searchParams.set('to', to);
  return url.pathname + url.search;
}
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
  drag.bars.forEach((bar) => bar.toggleAttribute('data-selecting', covered.has(bar)));
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
  markDrag(false);
  drag = null;
  if (covered.length < 2) return; // a click: the bar's own link
  const [from, to] = [covered[0], covered[covered.length - 1]];
  dragged = true;
  htmx.ajax('GET', rangeUrl(from.getAttribute('href'), to.dataset.to), { source: from });
});
document.addEventListener('click', (event) => {
  if (!dragged) return;
  dragged = false;
  if (!event.target.closest || !event.target.closest('[data-range]')) return;
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);

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
  return [...new Set([...ranged, ...searched].filter(Boolean))];
}
// Each list is watched once, and then only the rows that arrive (a stream's
// batch) are: nothing re-walks a list that only grows.
const watched = new WeakSet();
const rowsAdded = typeof MutationObserver === 'undefined' ? null : new MutationObserver((records) => {
  records.forEach((record) => {
    const rows = [...record.addedNodes].filter((node) => node.nodeType === 1);
    rows.forEach((row) => screenWatch?.observe(row));
    filterRows(rows, searchOf(record.target));
  });
  queueScreen();
});
function watchLists() {
  watchedLists().forEach((list) => {
    if (watched.has(list)) return;
    watched.add(list);
    for (const row of list.children) screenWatch?.observe(row);
    rowsAdded?.observe(list, { childList: true });
    filterRows([...list.children], searchOf(list));
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
    bars.forEach((bar) => bar.toggleAttribute('data-in-view', seen.has(bar)));
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
    if (query && list) rowsOnScreen(list).forEach((row) => ranges.push(...rangesIn(row, query)));
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
// ``rows`` shown or hidden by ``input``'s text, touching only those that change.
function filterRows(rows, input) {
  const needle = input ? input.value.trim().toLowerCase() : '';
  rows.forEach((row) => {
    const hide = Boolean(needle) && !textOf(row).includes(needle);
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
    filterRows([...list.children], input);
    keepInUrl(input, input.value.trim());
    queueScreen();
  });
});

// The dismissal rules, for the node tests (tests/web/test_app_js.py).
if (typeof module !== 'undefined') module.exports = { outsideClick, dismiss, navigates, markCurrent, rangeUrl, spanned, inView, splitMatches };
