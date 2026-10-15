/* Writes sql_tokens.json: each statement test_sql_read.py reads, parsed by
   the SQL grammar the editor loads and read by sql-read.js's tokensOf.

     npm i --prefix /tmp/cm @codemirror/lang-sql@6
     node tests/web/sql_tokens.cjs /tmp/cm */

const fs = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');

const { SQLite, PostgreSQL } = createRequire(`${path.resolve(process.argv[2])}/`)('@codemirror/lang-sql');
const { tokensOf } = require('../../app/components/web_frontend/static/js/sql-read.js');

const STATEMENTS = {
  sqlite: [
    'SELECT * FROM nope',
    'SELECT * FROM org o JOIN nope n ON n.id = o.id',
    'SELECT u.nope, email FROM user AS u',
    'WITH t AS (SELECT 1) SELECT * FROM t',
    'WITH t (a) AS MATERIALIZED (SELECT 1) SELECT * FROM t',
    'SELECT * FROM generate_series(1, 3)',
    'SELECT * FROM (SELECT id FROM org) AS s',
    'SELECT * FROM main.anything',
    'SELECT * FROM sqlite_master',
    'SELECT * FROM org WHERE id IS DISTINCT FROM name',
    'SELECT (1',
    "SELECT 'abc",
    'SELECT u.* FROM user u',
    'SELECT * FROM stt_usage WHERE detec',
    'SELECT * FROM user u JOIN org o ON o.id = u.id',
  ],
  postgresql: ['SELECT extract(EPOCH FROM at) FROM org', "SELECT E'a\\nb'"],
};
const DIALECTS = { sqlite: SQLite, postgresql: PostgreSQL };

const found = Object.fromEntries(Object.entries(STATEMENTS).map(([dialect, statements]) => [
  dialect,
  Object.fromEntries(statements.map((sql) => [
    sql, tokensOf(sql, DIALECTS[dialect].language.parser.parse(sql).topNode),
  ])),
]));
fs.writeFileSync(path.join(__dirname, 'sql_tokens.json'), `${JSON.stringify(found, null, 1)}\n`);
