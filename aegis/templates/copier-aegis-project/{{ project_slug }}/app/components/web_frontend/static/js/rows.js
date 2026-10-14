/* A table's rows (``rows_table``, pages/overseer/database/_macros.html),
   sorted and exported in the browser. A header button sorts the rows shown
   by its column, numbers as numbers, again for the other way (a header the
   server orders by, an indexed column on Rows, is a link instead, ordering
   the whole table). Export takes the rows shown as the page shows them (a
   long cell cut, a secret hidden): CSV or JSON downloaded, or copied, as
   those, as tab-separated text that pastes into a sheet's cells, or as a
   Markdown table. Copying and the toast are app.js's. */

// A cell a spreadsheet would run as a formula (=, +, -, @ first) becomes
// text, unless it is a number (-5).
function defused(value) {
  return /^[=+\-@\t\r]/.test(value) && Number.isNaN(Number(value)) ? `'${value}` : value;
}
function csvCell(value) {
  const cell = defused(value);
  return /[",\r\n]/.test(cell) ? `"${cell.replaceAll('"', '""')}"` : cell;
}
function toCsv(columns, rows) {
  return [columns, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n');
}
function toTsv(columns, rows) {
  const flat = (value) => defused(value).replace(/[\t\r\n]+/g, ' ');
  return [columns, ...rows].map((row) => row.map(flat).join('\t')).join('\n');
}
function toMarkdown(columns, rows) {
  const line = (row) => `| ${row.map((v) => v.replace(/[\r\n]+/g, ' ').replaceAll('|', '\\|')).join(' | ')} |`;
  return [line(columns), line(columns.map(() => '---')), ...rows.map(line)].join('\n');
}
// An object keeps one key of a name, so a second column of it (a join's
// ``u.id, o.id``) is named apart: ``id_2``.
function toJson(columns, rows) {
  const seen = new Map();
  const keys = columns.map((column) => {
    const times = (seen.get(column) || 0) + 1;
    seen.set(column, times);
    return times > 1 ? `${column}_${times}` : column;
  });
  return JSON.stringify(rows.map((row) => Object.fromEntries(keys.map((k, i) => [k, row[i]]))), null, 2);
}

// Numbers by value, then text in reading order (any case).
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
function compare(a, b) {
  const x = Number(a);
  const y = Number(b);
  const numbers = a !== '' && b !== '' && Number.isFinite(x) && Number.isFinite(y);
  if (numbers) return x - y;
  return collator.compare(a, b);
}

// The table a body belongs to, as columns and rows of text.
function rowsOf(body) {
  const columns = [...body.closest('table').tHead.rows[0].cells].map((th) => th.dataset.column);
  const rows = [...body.querySelectorAll(':scope > tr.log-row')]
    .map((tr) => [...tr.cells].map((td) => td.textContent.trim()));
  return { columns, rows };
}

// Each row with the line of its keys under it (``tr[data-links]``), kept
// together as the rows move.
function sortBody(body, index, desc) {
  const groups = [];
  [...body.children].forEach((tr) => {
    if (tr.classList.contains('log-row')) groups.push([tr]);
    else if (groups.length) groups[groups.length - 1].push(tr);
  });
  const keyed = groups.map((group) => [group[0].cells[index]?.textContent.trim() ?? '', group]);
  keyed.sort((a, b) => compare(a[0], b[0]) * (desc ? -1 : 1));
  body.append(...keyed.flatMap(([, group]) => group));
}

function save(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

// Each format: how the rows read in it, and its file's extension and type
// when it is downloaded (which ones are, export_menu says).
const FORMATS = {
  csv: { as: toCsv, ext: 'csv', type: 'text/csv' },
  json: { as: toJson, ext: 'json', type: 'application/json' },
  tsv: { as: toTsv, ext: 'tsv', type: 'text/tab-separated-values' },
  markdown: { as: toMarkdown, ext: 'md', type: 'text/markdown' },
};

if (typeof document !== 'undefined') {
  document.addEventListener('click', (event) => {
    const header = event.target.closest('[data-sort-rows]');
    if (!header) return;
    const th = header.closest('th');
    const desc = th.getAttribute('aria-sort') === 'ascending';
    [...th.parentElement.cells].forEach((cell) => {
      cell.removeAttribute('aria-sort');
    });
    th.setAttribute('aria-sort', desc ? 'descending' : 'ascending');
    sortBody(th.closest('table').tBodies[0], th.cellIndex, desc);
  });
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-export]');
    if (!button) return;
    const body = document.querySelector(button.dataset.exportRows);
    const found = body && rowsOf(body);
    if (!found || !found.rows.length) {
      toast('No rows to export', 'error');
      return;
    }
    const format = FORMATS[button.dataset.export];
    const text = format.as(found.columns, found.rows);
    if (button.dataset.exportTo === 'file') {
      save(`${button.dataset.exportName}.${format.ext}`, text, format.type);
      return;
    }
    copyText(text).then(
      () => toast(`Copied ${found.rows.length} rows`, 'ok'),
      () => toast('Could not copy - try a download instead', 'error'),
    );
  });
}

if (typeof module !== 'undefined') module.exports = { toCsv, toTsv, toJson, toMarkdown, compare, sortBody };
