# Database browser: rules and where each lives

Overseer > Database > Tables and Query (milestone 84). What it does for a
user is written once, in `docs/components/database.md` ("A table", "A
query"); this page does not repeat it. It lists the rules the code must
keep, each with its one home and the test that fails if it breaks. A
change that adds a second home for a rule, or a rule with no test, is the
bug.

Paths are under the template's `app/` and `tests/`.

## Who sees it

| Rule | Home | Test |
|---|---|---|
| Rows and Query are shown in dev, or once an admin turns on `OVERSEER_DATABASE_ROWS_ENABLED`; never on a deployed build without auth | `core/exposure.py` `refusal` | `core/test_exposure.py` |
| Every read checks it, not only the page | `db_rows.require_shown` (called by `page` and `db_query.run`) | `test_db_rows::test_hidden_where_rows_are_not_shown`, `test_db_query::test_hidden_where_rows_are_not_shown` |
| Query runs only for an admin (`overseer_actor`), every run audited, refused and stopped included | `routes/partials/overseer_database.py` `run_query` | `test_overseer_database::TestQuery`, `test_overseer_admin_gate::test_a_member_is_refused_everywhere` |
| Every Rows read is audited (`database.rows`), refused and stopped included, as the viewer from where they asked | `overseer_database_browser.rows`, through `SectionRequest.audit` (bound once in `routes/overseer.py` `audited`) | `TestRows::test_every_read_is_audited` |

## Nothing is written

| Rule | Home | Test |
|---|---|---|
| A write fails because the connection cannot write, never because the SQL was read: SQLite `query_only` plus an authorizer refusing ATTACH, DETACH, PRAGMA; PostgreSQL a read-only transaction | `db_rows.reading` | `test_db_query::test_a_write_fails`, `test_the_connection_goes_back_writable` |
| No read takes SQLite's write lock (the sync session factory) | `db_rows._app_engine` | `test_db_rows::test_reading_takes_no_write_lock` |
| Every read stops after `SECONDS` | `db_rows.reading` | `test_a_read_past_its_time_is_stopped`, `test_a_query_past_its_time_is_stopped` |
| PostgreSQL: no superuser outside dev; the connection is thrown away after each statement | `db_query._vet`, `db_query.run` | `test_postgres_refuses_a_superuser_outside_dev`, `test_postgres_throws_the_connection_away_after_each_statement` |

## No secret leaves the database

| Rule | Home | Test |
|---|---|---|
| What is a secret: text or bytes named like one (`redact.SECRET`, `ciphertext`, `*_encrypted`), read from every model | `db_rows.masked`, `db_rows.models` | `test_every_model_counts_though_none_was_imported_yet`, `test_secrets_are_read_from_every_table` |
| Rows select a secret as `HIDDEN`, never its value | `db_rows._selected` | `test_a_secret_never_leaves_the_database`, `test_a_secret_never_reaches_the_page` |
| A secret cannot be sorted or filtered by (either would spell it out) | `db_rows.sortable`, `db_filters.filterable` | `test_a_secret_cannot_be_sorted_or_filtered_by` |
| Text and flags are matched (= or ≠), never ordered: the page offers only what `operators` allows, and the server refuses the rest (a URL edited by hand). One function, no request | `db_filters.operators` (used by `conditions` and the page's `rows_allowed`) | `test_db_filters::test_a_column_is_asked_what_its_kind_allows`, `test_json_is_not_filtered_and_text_is_only_matched`, `TestRows::test_a_filter_is_a_column_picked_and_a_value` |
| Query on SQLite reads a secret column as empty however the statement reaches it; on PostgreSQL a plan reading a table with a secret is refused | `db_rows._authorizer`, `db_query.secret_read` | `test_a_secret_renamed_is_never_read`, `test_postgres_refuses_a_plan_reading_a_table_with_a_secret` |
| Every cell is redacted, then cut | `db_rows.cell` | `test_a_long_cell_is_redacted_then_cut`, `test_cells_are_redacted_and_cut` |

## Only what the app declares

| Rule | Home | Test |
|---|---|---|
| A table is looked up by name among the models, never put into SQL | `db_rows.table_of` | `test_only_a_table_the_models_declare_is_read` |
| Sorted only where an index serves it; offset pages capped at `MAX_DEPTH`; ties broken by the key | `db_rows.sortable`, `db_rows.page` | `test_another_order_pages_by_offset_only_where_indexed`, `test_pages_by_offset_go_only_so_deep`, `test_pages_by_a_column_with_ties_break_them_by_key` |
| A filter's value is read as its column's kind; a filter the URL could not carry back is refused | `db_filters.value`, `db_filters.ask` | `test_a_value_is_read_as_its_columns_kind`, `test_a_filter_asked_is_one_the_text_carries_back` |
| A row leads only where its key's value can be asked for | `db_rows.follow` | `test_only_a_value_the_filter_can_ask_for_is_followed` |

## The editor (browser only, no request)

| Rule | Home | Test |
|---|---|---|
| Marks the grammar's errors, an unclosed quote, an unknown table. Columns are the database's to check | `static/js/sql-read.js` `problems` | `web/test_sql_read.py`, on real grammar output (`sql_tokens.json`, rebuilt by `sql_tokens.cjs`) |
| Offers the columns of the tables the statement reads | `sql-read.js` `columnsRead` | `test_sql_read::test_the_columns_offered_are_the_tables_read` |
| Tabs are kept in this browser only | `static/js/sql.js` `load`/`keep` | `web/test_sql_js.py` |
| The page scripts share one global scope: no name declared twice | `static/js/*.js` | `test_app_js::test_the_page_scripts_declare_no_name_twice` |

## Decided against

- Checking `alias.column` in the editor: guessing which table an alias means
  broke on subqueries and reused aliases. The database names the missing
  column when the statement runs.
- Asking the server which comparisons a column allows: the rule is sent
  with the page.
