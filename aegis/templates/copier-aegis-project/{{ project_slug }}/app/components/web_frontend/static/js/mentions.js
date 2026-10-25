/* A path card's parts named in Illiana's words (partials/chat/cards/path.html).
   Each part the card draws is named by its title (Authentication) or its
   own name (auth); nothing else matches, so a part the card does not draw
   is never lit. A settled answer marks each name it says in place: hover
   or tap it and the card lights that part and its lines, still. On a call
   (voice.js), the card lights the part she named last as she says it,
   and an answer heard again (its Listen button) lights as it plays.
   Pure matching first (tests/js/mentions.test.js), then the page. */
(() => {
  // The names each part goes by: its title, and its own name off its map
  // key (``service_auth``: auth; ``outside:Stripe``: Stripe).
  function partsOf(nodes) {
    return nodes.map(({ key, title }) => {
      const own = key.replace(/^(service_|outside:)/, '').replace(/_/g, ' ');
      return { key, words: [...new Set([title, own].filter(Boolean))] };
    });
  }

  const escaped = (word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  // Each name of ``parts`` to its part, and the pattern that finds them
  // (the longest name first where two overlap): built once a card, not on
  // every word she says.
  const matchers = new WeakMap();
  function matcher(parts) {
    if (!matchers.has(parts)) {
      const named = new Map();
      for (const { key, words } of parts) for (const word of words) named.set(word.toLowerCase(), key);
      const names = [...named.keys()].sort((a, b) => b.length - a.length).map(escaped);
      const pattern = names.length && new RegExp(`(?<![\\w-])(${names.join('|')})(?![\\w-])`, 'gi');
      matchers.set(parts, { named, pattern });
    }
    return matchers.get(parts);
  }

  // Every whole-word name of ``parts`` in ``text``, in order: where it is
  // and which part it names.
  function namesIn(text, parts) {
    const { named, pattern } = matcher(parts);
    if (!pattern) return [];
    return [...text.matchAll(pattern)].map((found) => ({
      start: found.index,
      end: found.index + found[0].length,
      key: named.get(found[0].toLowerCase()),
    }));
  }

  // The part named last in ``text``, or null.
  function lastNamed(text, parts) {
    const found = namesIn(text, parts);
    return found.length ? found[found.length - 1].key : null;
  }

  // The part named ``share`` of the way through ``text`` (0..1): an
  // answer heard again has no word timings, so an even pace.
  function namedAt(text, share, parts) {
    return lastNamed(text.slice(0, Math.round(share * text.length)), parts);
  }

  const mentions = { partsOf, namesIn, lastNamed, namedAt };
  if (typeof module !== 'undefined') {
    module.exports = mentions;
    return;
  }

  // --- The page ---------------------------------------------------------
  const CARD = '[data-card="path"]';
  // A card's parts, read off it once: what it draws does not change.
  const drawn = new WeakMap();
  const cardParts = (card) => {
    if (!drawn.has(card)) {
      drawn.set(card, partsOf(
        [...card.querySelectorAll('[data-node]')].map((node) => ({
          key: node.dataset.node,
          title: node.querySelector('[data-title]')?.textContent.trim() || '',
        })),
      ));
    }
    return drawn.get(card);
  };

  // ``key``'s part and its lines lit on ``card`` (none: nothing lit); the
  // part already lit is left as it is.
  const lit = new WeakMap();
  function light(card, key) {
    if ((lit.get(card) ?? null) === key) return;
    lit.set(card, key);
    card.querySelectorAll('[data-lit]').forEach((el) => { el.removeAttribute('data-lit'); });
    if (!key) return;
    const at = CSS.escape(key);
    card
      .querySelectorAll(`[data-node="${at}"], .map-link[data-from="${at}"], .map-link[data-to="${at}"]`)
      .forEach((el) => { el.setAttribute('data-lit', ''); });
  }

  // The names in a settled answer's text, each marked in place for
  // ``card`` to light (code and links left as they are).
  function mark(card) {
    const body = card.closest('[data-role="assistant"]')?.querySelector('[data-body]');
    if (!body || body.closest('[data-stream]') || body.hasAttribute('data-named')) return;
    body.setAttribute('data-named', '');
    const parts = cardParts(card);
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
      acceptNode: (text) => (text.parentElement.closest('code, pre, a') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const texts = [];
    while (walker.nextNode()) texts.push(walker.currentNode);
    texts.forEach((text) => {
      const found = namesIn(text.data, parts);
      if (!found.length) return;
      const pieces = document.createDocumentFragment();
      let at = 0;
      found.forEach(({ start, end, key }) => {
        pieces.append(text.data.slice(at, start));
        const name = document.createElement('span');
        name.dataset.mention = key;
        name.tabIndex = 0;
        name.textContent = text.data.slice(start, end);
        pieces.append(name);
        at = end;
      });
      pieces.append(text.data.slice(at));
      text.replaceWith(pieces);
    });
  }

  // The named part an event is on, and its card: its answer's.
  const mentionAt = (event) => {
    const name = event.target.closest?.('[data-mention]');
    return [name, name?.closest('[data-role="assistant"]')?.querySelector(CARD)];
  };
  let held = null;
  const hover = (on) => (event) => {
    const [name, card] = mentionAt(event);
    if (card && !held) light(card, on ? name.dataset.mention : null);
  };
  document.addEventListener('mouseover', hover(true));
  document.addEventListener('focusin', hover(true));
  document.addEventListener('mouseout', hover(false));
  document.addEventListener('focusout', hover(false));
  // A tap holds it lit (a touch screen has no hover); again, or another, lets go.
  document.addEventListener('click', (event) => {
    const [name, card] = mentionAt(event);
    if (!card) return;
    const same = held === name;
    held = same ? null : name;
    light(card, same ? null : name.dataset.mention);
  });
  document.addEventListener('htmx:load', (event) => {
    const root = event.detail.elt;
    [...(root.matches?.(CARD) ? [root] : []), ...(root.querySelectorAll?.(CARD) || [])].forEach(mark);
  });

  // On a call: the part she named last in ``said`` (her words so far)
  // lit on ``card`` (the one she drew for this answer; voice.js knows it).
  function follow(card, said) {
    if (card) light(card, lastNamed(said, cardParts(card)));
  }

  // An answer heard again (its Listen button), ``share`` of the way
  // through: the part named there lit on its card; null, nothing.
  function along(answer, share) {
    const card = answer?.querySelector(CARD);
    const body = answer?.querySelector('[data-body]');
    if (!card || !body) return;
    light(card, share == null ? null : namedAt(body.textContent, share, cardParts(card)));
  }

  window.mentions = { follow, along };
})();
