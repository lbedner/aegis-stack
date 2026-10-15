/* A statement in the Query editor (sql.js) read as you type, with no
   request, from its tokens: the SQL grammar's nodes at its top level, a
   ``Parens`` holding its own as ``children`` (``tokensOf``).

   ``problems`` marks what is wrong: the grammar's own errors, a quote left
   open, a table the schema lacks. A column is not checked, bare or through
   an alias: which table it is from takes the database. ``columnsRead``
   offers the columns of the tables the statement reads. */

const TABLE_AFTER = new Set(['from', 'join', 'update', 'into']);
// What a database keeps of its own, never in the schema (SQLite's
// sqlite_master, PostgreSQL's pg_ catalogs).
const CATALOG = /^(sqlite_|pg_|information_schema)/i;
const unquoted = (text) => (/^["`[]/.test(text) ? text.slice(1, -1) : text);
const isWord = (token, words) => words.test(token?.text ?? '');
// A quote left open: the text from its first quote (PostgreSQL's E'...' and
// the like have a letter before it) not ending with that quote.
function unclosed(text) {
  const open = text.search(/['"`$]/);
  return open < 0 || text.length - open < 2 || text.at(-1) !== text[open];
}
function walk(tokens, visit) {
  tokens.forEach((token, index) => {
    visit(token, index, tokens);
    if (token.children) walk(token.children, visit);
  });
}
function lowered(schema) {
  return new Map(Object.entries(schema).map(([table, columns]) => [table.toLowerCase(), columns]));
}
// A WITH's name at ``i``: its columns maybe, AS, [NOT] MATERIALIZED maybe,
// then its query.
function isNamed(run, i) {
  let j = run[i + 1]?.name === 'Parens' ? i + 2 : i + 1;
  if (!isWord(run[j], /^as$/i)) return false;
  j += 1;
  while (isWord(run[j], /^(not|materialized)$/i)) j += 1;
  return run[j]?.name === 'Parens';
}
// The tables a statement names (``known``: the schema's, lowered): those
// it reads, and those the schema lacks.
function readSql(tokens, known) {
  const named = new Set(); // WITH's names
  const tables = new Set();
  const unknown = [];
  // The tables a FROM (or JOIN, ...) names, comma after comma, each with
  // its alias; a subquery, or a function read as one, skipped.
  const readTables = (run, start) => {
    for (let j = start; j < run.length; j += 1) {
      const token = run[j];
      if (token.name === 'Parens') {
        // a subquery
      } else if (run[j + 1]?.name === 'Parens') {
        j += 1; // a function and its arguments
      } else {
        const name = unquoted(token.text.split('.').at(-1));
        const table = name.toLowerCase();
        const nameable = ['Identifier', 'QuotedIdentifier', 'CompositeIdentifier'].includes(token.name);
        if (!nameable && !(token.name === 'Keyword' && known.has(table))) return;
        // A schema's (main.x) or the database's own is not the app's to check.
        if (!known.has(table) && token.name !== 'CompositeIdentifier' && !CATALOG.test(table)) {
          unknown.push({ token, name });
        }
        tables.add(table);
        if (isWord(run[j + 1], /^as$/i)) j += 1;
        if (run[j + 1]?.name === 'Identifier') j += 1; // its alias
      }
      if (run[j + 1]?.text !== ',') return;
      j += 1;
    }
  };
  walk(tokens, (token, i, run) => {
    if (['Identifier', 'QuotedIdentifier'].includes(token.name) && isNamed(run, i)) {
      named.add(unquoted(token.text).toLowerCase());
    }
    // FROM names tables in a statement's clauses (its top level, or a
    // subquery's), not in a function's (EXTRACT(EPOCH FROM at)) or after
    // IS DISTINCT.
    const clauses = run === tokens || isWord(run[1], /^(select|with)$/i);
    if (token.name === 'Keyword' && TABLE_AFTER.has(token.text.toLowerCase())
      && clauses && !isWord(run[i - 1], /^distinct$/i)) {
      readTables(run, i + 1);
    }
  });
  return { tables, missing: unknown.filter(({ name }) => !named.has(name.toLowerCase())) };
}

// What is wrong in a statement: each with where it is, how bad, and why.
function problems(tokens, schema) {
  const found = readSql(tokens, lowered(schema)).missing.map(({ token, name }) => ({
    from: token.from, to: token.to, severity: 'warning', message: `No table ${name}`,
  }));
  walk(tokens, (token) => {
    if (token.name === '⚠') {
      found.push({ from: token.from, to: token.to, severity: 'error', message: 'Syntax error' });
    } else if (['String', 'QuotedIdentifier'].includes(token.name) && unclosed(token.text)) {
      found.push({ from: token.from, to: token.to, severity: 'error', message: 'Unclosed quote' });
    }
  });
  return found.sort((x, y) => x.from - y.from);
}

// The columns of the tables a statement reads, for the editor to offer
// where a bare name is typed (the SQL language offers ``table.`` columns,
// tables and keywords): each named for its table.
function columnsRead(tokens, schema) {
  const known = lowered(schema);
  const tables = [...readSql(tokens, known).tables].filter((t) => known.has(t));
  return tables.flatMap((table) => known.get(table).map((column) => ({ label: column, detail: table })));
}

// A statement's tokens (``text``, its syntax tree's ``node``) as the above
// read them.
function tokensOf(text, node) {
  const out = [];
  for (let child = node.firstChild; child; child = child.nextSibling) {
    const token = { name: child.name, text: text.slice(child.from, child.to), from: child.from, to: child.to };
    if (child.name === 'Parens') token.children = tokensOf(text, child);
    out.push(...(child.name === 'Statement' ? tokensOf(text, child) : [token]));
  }
  return out;
}

if (typeof module !== 'undefined') module.exports = { problems, columnsRead, tokensOf };
