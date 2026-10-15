/* SQL editor island (after charts and chat).

   Overseer > Database > Query renders a plain box in a [data-sql-editor]
   that carries the database's dialect and each table's columns
   (overseer_database_browser.query_page); this file mounts CodeMirror on
   load and after each htmx settle: highlighted in that dialect (the tok-*
   classes, coloured in input.css as code blocks are), completing keywords,
   tables and columns. The box stays the form's field, hidden and kept in
   step, so without the script it is still a box. Cmd-Enter runs the
   statement; Tab takes the completion open (without one, it leaves the
   editor). What is wrong is marked as you type, and the columns offered
   are the statement's tables', read with no request (sql-read.js).

   Its [data-sql-workbench] keeps the statements as tabs in this browser
   (localStorage, once typing pauses: what was typed survives a reload, on
   this machine only), each with its last answer while the page is open; a
   seed (from a table, named for it) opens one more, or the tab already
   holding it. + opens a tab, a double click renames one, x closes it.

   CodeMirror is fetched on first use (or as a link to Query is pointed
   at) from the app itself: one pinned bundle (static/vendor/codemirror.js,
   how to rebuild it at its top), whose URL the script tag carries
   (data-codemirror, fingerprinted in a build). Nothing from another origin
   runs unverified, and a dynamic import() could not carry a hash. */

const KEY = 'aegis-sql-tabs';
const CODEMIRROR = typeof document !== 'undefined' ? document.currentScript?.dataset.codemirror : undefined;

let loading = null;
function codeMirror() {
  if (!loading) loading = import(CODEMIRROR);
  return loading;
}

// What every tab's editor shares: the dialect and schema the box carries,
// the keys, what is wrong marked, and ``changed`` told of each edit.
function extensions(cm, box, run, changed) {
  const schema = JSON.parse(box.dataset.schema || '{}');
  const dialect = box.dataset.dialect === 'postgresql' ? cm.PostgreSQL : cm.SQLite;
  const tokens = (state) => tokensOf(state.doc.toString(), cm.syntaxTree(state).topNode);
  return [
    cm.highlightSpecialChars(),
    cm.history(),
    cm.drawSelection(),
    cm.keymap.of([...cm.defaultKeymap, ...cm.historyKeymap]),
    cm.sql({ dialect, schema, upperCaseKeywords: true }),
    // ... and the columns of the tables this statement reads, first.
    dialect.language.data.of({
      autocomplete: (context) => {
        const word = context.matchBefore(/\w*/);
        if (!word || (word.from === word.to && !context.explicit)) return null;
        if (context.state.sliceDoc(word.from - 1, word.from) === '.') return null;
        const options = columnsRead(tokens(context.state), schema)
          .map((o) => ({ ...o, type: 'property', boost: 2 }));
        return options.length ? { from: word.from, options, validFor: /^\w*$/ } : null;
      },
    }),
    cm.linter((view) => problems(tokens(view.state), schema), { delay: 400 }),
    cm.syntaxHighlighting(cm.classHighlighter),
    cm.autocompletion(),
    cm.closeBrackets(),
    cm.placeholder(box.querySelector('[name]').placeholder),
    cm.EditorView.lineWrapping,
    cm.Prec.highest(cm.keymap.of([
      { key: 'Tab', run: cm.acceptCompletion },
      { key: 'Mod-Enter', run },
    ])),
    cm.EditorView.updateListener.of((update) => {
      if (update.docChanged) changed(update.state.doc.toString());
    }),
  ];
}

// The tabs as last kept, or one empty one. Storage can be refused (a
// private window): the tabs then last as long as the page.
function load() {
  try {
    const kept = JSON.parse(localStorage.getItem(KEY));
    if (kept?.tabs?.length) return kept;
  } catch (error) {
    console.warn('SQL tabs not read; starting afresh', error);
  }
  return { tabs: [{ id: 1, name: 'Query 1', sql: '' }], active: 1 };
}
function keep(book) {
  try {
    localStorage.setItem(KEY, JSON.stringify(book));
  } catch (error) {
    console.warn('SQL tabs not kept', error);
  }
}
// Typing keeps the tabs once it pauses, not on every key; leaving the page
// or the section keeps what is pending at once.
let pending = null;
let pendingTimer = 0;
function keepSoon(book) {
  pending = book;
  clearTimeout(pendingTimer);
  pendingTimer = setTimeout(flush, 300);
}
function flush() {
  if (pending) keep(pending);
  pending = null;
}
// An answer as kept: its nodes, or the HTML of one that landed while its tab
// was left (and the empty scroller before any run).
function restore(answer, kept) {
  if (typeof kept !== 'string') {
    answer.replaceChildren(...kept);
    return;
  }
  const parsed = document.createElement('template');
  parsed.innerHTML = kept;
  answer.replaceChildren(parsed.content);
}
// A table's statement (from Tables) as a tab named for it, open: the tab
// already holding it, or one more.
function seeded(book, seed, name) {
  const held = book.tabs.find((tab) => tab.sql === seed);
  book.active = held ? held.id : nextId(book);
  if (!held) book.tabs.push({ id: book.active, name, sql: seed });
  return book;
}
function nextId(book) {
  return Math.max(0, ...book.tabs.map((tab) => tab.id)) + 1;
}
function button(text, label, extra) {
  const el = document.createElement('button');
  el.type = 'button';
  el.textContent = text;
  el.title = label;
  el.setAttribute('aria-label', label);
  el.className = extra;
  return el;
}

function workbench(root, cm) {
  const box = root.querySelector('[data-sql-editor]');
  const field = box?.querySelector('[name]');
  if (!field || !root.isConnected) return;
  const nav = root.querySelector('[data-sql-tabs]');
  const answer = root.querySelector('#database-query-answer');
  const form = field.form;
  const blank = answer.innerHTML;
  const book = load();
  if (root.dataset.seed) {
    seeded(book, root.dataset.seed, root.dataset.seedName);
    const url = new URL(window.location.href);
    url.searchParams.delete('table');
    window.history.replaceState(window.history.state, '', url);
  }
  const current = () => book.tabs.find((tab) => tab.id === book.active) || book.tabs[0];
  const states = new Map(); // a tab's editor (its text, undo, selection)
  const answers = new Map(); // a tab's last answer, while the page is open
  const run = () => {
    form.requestSubmit();
    return true;
  };
  const shared = extensions(cm, box, run, (text) => {
    field.value = text;
    current().sql = text;
    keepSoon(book);
  });
  const stateOf = (tab) => {
    if (!states.has(tab.id)) states.set(tab.id, cm.EditorState.create({ doc: tab.sql, extensions: shared }));
    return states.get(tab.id);
  };
  const view = new cm.EditorView({ parent: box, state: stateOf(current()) });
  field.hidden = true;

  function show(id) {
    book.active = id;
    const tab = current();
    view.setState(stateOf(tab));
    field.value = tab.sql;
    restore(answer, answers.get(tab.id) ?? blank);
    keep(book);
    draw();
    view.focus();
  }
  function open(id) {
    states.set(book.active, view.state);
    answers.set(book.active, [...answer.childNodes]);
    show(id);
  }
  function close(id) {
    const at = book.tabs.findIndex((tab) => tab.id === id);
    book.tabs.splice(at, 1);
    states.delete(id);
    answers.delete(id);
    if (book.active === id) show((book.tabs[at] || book.tabs[at - 1]).id);
    else {
      keep(book);
      draw();
    }
  }
  function rename(tab, label) {
    const input = document.createElement('input');
    input.value = tab.name;
    input.className = 'sql-tab-name';
    input.setAttribute('aria-label', 'Tab name');
    label.replaceWith(input);
    input.select();
    let done = false;
    const finish = (save) => {
      if (done) return;
      done = true;
      if (save && input.value.trim()) tab.name = input.value.trim();
      keep(book);
      draw();
    };
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') finish(true);
      if (event.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', () => finish(true));
  }
  function tabOf(tab) {
    const el = document.createElement('div');
    el.className = 'tab sql-tab';
    el.setAttribute('role', 'tab');
    el.setAttribute('aria-selected', String(tab.id === book.active));
    const label = document.createElement('span');
    label.textContent = tab.name;
    el.append(label);
    if (book.tabs.length > 1) {
      const x = button('×', `Close ${tab.name}`, 'sql-tab-close');
      x.addEventListener('click', () => close(tab.id));
      el.append(x);
    }
    el.addEventListener('click', (event) => {
      if (!event.target.closest('button, input') && tab.id !== book.active) open(tab.id);
    });
    label.addEventListener('dblclick', () => rename(tab, label));
    return el;
  }
  function draw() {
    const add = button('+', 'New statement', 'sql-tab-new');
    add.addEventListener('click', () => {
      const id = nextId(book);
      book.tabs.push({ id, name: `Query ${id}`, sql: '' });
      open(id);
    });
    nav.replaceChildren(...book.tabs.map(tabOf), add);
  }

  // An answer that lands after its tab was left is kept for that tab.
  let asked = null;
  form.addEventListener('htmx:beforeRequest', () => {
    asked = book.active;
  });
  form.addEventListener('htmx:beforeSwap', (event) => {
    if (asked === book.active) return;
    // Closed since: dropped, or a tab given its id later would show it.
    if (book.tabs.some((tab) => tab.id === asked)) answers.set(asked, event.detail.serverResponse);
    event.detail.shouldSwap = false;
  });

  field.value = current().sql;
  keep(book);
  draw();
  view.focus();
}

function mountWorkbench() {
  const bench = document.getElementById('database-query');
  if (!bench || bench.dataset.mounted) return;
  bench.dataset.mounted = 'true';
  codeMirror().then(
    (cm) => {
      workbench(bench, cm);
    },
    (error) => console.warn('SQL editor not loaded; the plain box stays', error),
  );
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', mountWorkbench);
  document.body.addEventListener('htmx:afterSettle', mountWorkbench);
  document.body.addEventListener('htmx:beforeSwap', flush);
  // Pointed at a link to Query: start fetching, so the editor is ready.
  document.addEventListener('pointerover', (event) => {
    if (!event.target.closest?.('a[href*="/database/query"], [data-query-table]')) return;
    codeMirror().catch((error) => console.warn('SQL editor not fetched ahead', error));
  });
  window.addEventListener('pagehide', flush);
}

if (typeof module !== 'undefined') module.exports = { load, seeded };
