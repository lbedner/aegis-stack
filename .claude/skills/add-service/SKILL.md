---
name: add-service
description: Use when adding a new service (a business capability like auth, AI, blog, or finance) to the Aegis Stack framework itself. Covers the plugin-spec registry, migrations, CLI, template, dashboard, test, docs, and i18n files that must change together.
---

# Add service

Adds a new service (business logic, e.g. blog, finance, auth) to the framework
so generated projects can select it via `aegis init --services` or add it
later via `aegis add-service`. Traced from the two most recent services,
`blog` and `finance`.

## When to use

Use when the task is "add a new service to Aegis Stack" (a business
capability under `app/services/<name>/`, selected via `include_<name>` in
`copier.yml`).

Do NOT use for adding a **component** (infrastructure: worker, scheduler,
database, redis, ingress, observability) - components live in
`aegis/core/components.py` and share the same `PluginSpec` shape but a
different file footprint. Do NOT use for changing behavior inside an
existing service; that is ordinary feature work, not this skill.

## Files that change

Registry (`ServiceSpec` is a thin alias of `PluginSpec` pinned to
`kind=SERVICE`; see `aegis/core/plugins/spec.py`):

- `aegis/core/services.py`: add a `ServiceSpec` entry to the `SERVICES` dict.
  Set `type` (add a new `ServiceType` member only if none fit),
  `description`/`long_description`, `required_components`,
  `recommended_components`, `pyproject_deps`, `template_files` (display list),
  `marker_path` (the path `aegis update` uses to detect the service on disk),
  and `docs_path` (leave `""` until the docs page ships - a non-empty value
  is pinned by `tests/core/test_spec_docs_paths.py`).
- `aegis/core/services.py`: `wiring=PluginWiring(...)` on the spec - declares
  `routers` (`RouterWiring`), `dashboard_cards`/`dashboard_modals`
  (`FrontendWidgetWiring`), and `deps_providers` (`SymbolWiring`). This
  metadata mirrors, and must stay in sync with, the hand-written Jinja
  conditionals in the template files below - it does not currently drive
  their rendering for in-tree services.
- `aegis/core/services.py`: `files=FileManifest(primary=[...], extras={...})`
  - every path the service owns. `primary` is the add/init base;
    `compute_file_mapping()` derives `post_gen_tasks.get_component_file_mapping()`
    from this, so there is no separate hand-maintained mapping to edit.
- `aegis/core/migration_generator.py`: only if the service owns tables, add a
  `ServiceMigrationSpec` (built from `TableSpec`/`ColumnSpec`/`IndexSpec`/
  `ForeignKeySpec`/`CheckConstraintSpec`) as a module-level constant (see
  `BLOG_MIGRATION`, `FINANCE_MIGRATION`) and reference it from the spec's
  `migrations=[...]` list in `services.py`. Import the plugin-facing aliases
  from `aegis/core/migration_spec.py` if writing from outside this module.
  `MIGRATION_SPECS` is derived lazily from every spec's `.migrations` via
  `collect_migrations()` - no dict entry to hand-maintain.
- `aegis/constants.py`: `AnswerKeys` - add `<NAME> = "include_<name>"` and
  `SERVICE_<NAME> = "<name>"`. Add any sub-flag keys the service needs (see
  `FINANCE_PLAID`, `FINANCE_SNAPTRADE`, `FINANCE_IMPORT`).
- `copier.yml` (repo root, not under `templates/`): add the `include_<name>`
  bool question, plus any per-service config questions gated with
  `when: "{{ include_<name> }}"` (model on `finance_plaid`). Extend
  `_include_migrations` if the service owns tables.
- `aegis/core/<name>_service_parser.py`: only if the service takes bracket
  syntax like `<name>[option]` (model on `ai_service_parser.py`,
  `auth_service_parser.py`, `insights_service_parser.py`; blog and finance
  need none of this - they have no `options=` on their spec). Wire it into
  `aegis/core/service_resolver.py` if it introduces a cross-service
  dependency check (see the `insights[per_user]` requires `auth[org]` block).
- `aegis/cli/interactive.py`: `interactive_<name>_service_config()` only if
  the service needs an interactive config prompt during `aegis add-service
  --interactive` (model on `interactive_ai_service_config`; not needed for
  blog/finance).

Generation and update plumbing (thread the new `AnswerKeys.<NAME>` answer key
through the generate and update flows; a table-owning service that skips these
generates fine but breaks migrations on `aegis update`):

- `aegis/core/template_generator.py`: add an `AnswerKeys.<NAME>: "yes"/"no"`
  entry to the answer dict built from `selected_services` (model on the
  existing per-service entries using `extract_base_service_name`).
- `aegis/core/copier_manager.py`: add `AnswerKeys.<NAME>` to the template
  context booleans, and if the service owns tables include it in the
  `needs_migration_files` detection.
- `aegis/core/copier_updater.py` and `aegis/commands/update.py`: add
  `include_<name> = answers.get(AnswerKeys.<NAME>, False)` and OR it into the
  aggregate migration/needs check used during update.
- `aegis/core/manual_updater.py`: add `AnswerKeys.<NAME>` to the answer-keys
  list it threads through add/remove.

CLI (framework commands, not the generated project's CLI):

- `aegis/commands/add_service.py`: resolves service deps to components,
  prompts for config, calls `ManualUpdater.add_component`, generates
  migrations via `generate_migration`/`bootstrap_alembic`. Only add a
  service-specific branch here if the service needs bracket-syntax parsing
  or extra answer keys threaded through (auth, ai, insights do; blog and
  finance need none).
- `aegis/commands/remove_service.py`: calls `ManualUpdater.remove_component`;
  no per-service branch needed unless the service needs a custom warning
  (see the auth-specific data-loss warning block).
- `aegis/commands/services.py`: the `aegis services` list command reads
  `SERVICES`/`ServiceType` automatically; no edit needed unless a new
  `ServiceType` header is required.

Template (`aegis/templates/copier-aegis-project/{{ project_slug }}/`):

- `app/services/<name>/`: the service package (business logic, `deps.py` for
  the FastAPI dependency provider referenced by `wiring.deps_providers`).
- `app/components/backend/api/<name>/`: routes, registered in
  `app/components/backend/api/routing.py.jinja` behind a full-body
  `{%- if include_<name> %}` import + `app.include_router(...)` block.
- `app/cli/<name>.py.jinja`: the project's `<name>` subcommand. Register it
  in `app/cli/main.py.jinja` with the existing
  `try: importlib.import_module(...) / except ImportError: pass` pattern.
- Dashboard card: `app/components/frontend/dashboard/cards/<name>_card.py`,
  exported from `cards/__init__.py.jinja` behind `{%- if include_<name> %}`,
  and added to the aggregate `{%- if include_auth or ... or include_<name>
  or _plugins %}` gate in that same file (guards `ServicesCard`'s import).
- Dashboard modal: `app/components/frontend/dashboard/modals/<name>_modal.py`,
  exported from `modals/__init__.py.jinja`, and added to the `modal_map` and
  import block in `dashboard/cards/card_utils.py.jinja` (key convention:
  `"service_<name>"`, matching `wiring.dashboard_cards[0].modal_id`).
- The card/modal also need registering in the surrounding frontend wiring, each
  behind `{%- if include_<name> %}`: `dashboard/status_overview.py.jinja` (the
  status grid), `app/components/frontend/main.py.jinja` (the frontend app that
  mounts the card), `app/services/system/ui.py.jinja` (dashboard registry), and
  `app/components/backend/api/deps.py.jinja` if the service's routes need a
  shared dependency. Trace how `blog` appears in each before adding `<name>`.
- `app/components/backend/startup/component_health.py.jinja`: register the
  service's health check behind `{%- if include_<name> %}` with
  `register_service_health_check("<name>", check_<name>_service_health)`.
- `app/components/backend/startup/database_init.py.jinja` (table-owning
  services only): import the service's SQLModel models behind
  `{%- if include_<name> %}` (with `# noqa: F401`), add `include_<name>` to the
  `needs_migrations` set expression, and add a `"<name>": ("table",
  "<table>")` entry to the existing-table stamp map. Skipping this means the
  service's tables are never created or stamped.
- `alembic/env.py.jinja` (table-owning services only): import the models behind
  `{%- if include_<name> %}` so Alembic autogenerate sees them.
- `pyproject.toml.jinja`: gate service-specific dependencies behind
  `{%- if include_<name> %}`. If the service owns tables, add it to the
  shared `alembic==1.16.5` gate condition (the big `{%- if include_auth or
  ... or include_<name> %}` line).
- `docs/services/<name>/` under the template tree is a separate, optional
  convention (ships docs inside the generated project itself); only `comms`
  has it today. Do not treat it as required.

Framework docs (this repo's own `/docs`, published via the root `mkdocs.yml`
- distinct from the template docs above, and what `ServiceSpec.docs_path`
points at):

- `docs/services/<name>/index.md` (+ `cli.md`, `api.md`, `dashboard.md`,
  `examples.md`, `setup.md` as applicable - see `docs/services/blog/` and
  `docs/services/payment/` for the current shape).
- `mkdocs.yml` (repo root): add a `Services: - <Name>:` nav block pointing at
  the new pages (see the `blog`/`payment`/`insights` entries).
- `aegis/core/services.py`: set `docs_path="services/<name>"` on the spec
  once the pages exist (leave `""` until then, per above).

Tests (generated-project template tests, under
`aegis/templates/copier-aegis-project/{{ project_slug }}/`):

- `tests/services/<name>/test_<name>_service.py` (or
  `tests/services/test_<name>_service.py` for a small service): unit tests
  for the service's business logic (write first, TDD).
- `tests/api/test_<name>_endpoints.py`: only if the service exposes routes.
- Template-render test (framework side, optional): if the service's template
  has non-trivial cross-service Jinja branching (e.g. blog's router renders
  differently with auth on/off/rbac), add a
  `tests/core/test_<name>_template_render.py` that renders the `.jinja` file
  directly via `Environment(loader=FileSystemLoader(get_template_path()))`
  and asserts on the rendered source (see `tests/core/test_blog_template_render.py`).

Tests (this repo's own CLI/core test suite):

- `tests/core/test_services.py`: add a spec-shape test class (name, type,
  required/recommended components, `pyproject_deps`) and a
  `test_<name>_service_wiring` test asserting `spec.wiring.routers[0].module`,
  `.alias`, and the dashboard `modal_id`s (mirrors `test_blog_service_wiring`).
- `tests/cli/test_services_cli.py`: extend the `aegis services` list-command
  coverage tables with the new service's expected inclusion/exclusion flags.
- `tests/cli/conftest.py`: add a `<name>_with_database` (or similarly named)
  entry to `NAMED_PROJECT_SPECS` so downstream tests copy a cached project
  instead of regenerating one (`tests/CLAUDE.md` explains the cache; skipping
  this entry costs 10+ minutes of CI time). Also add the new stack to
  `tests/cli/test_stack_generation.py`'s `STACK_COMBINATIONS` and to the
  `everything` entry in `NAMED_PROJECT_SPECS`.
- `tests/cli/test_add_service_importable.py`: add the service name (with
  bracket options if it would otherwise prompt interactively) to
  `SERVICE_INVOCATIONS`. This is the regen-gap guard: it runs
  `aegis add-service <name>` against a cached base project and imports the
  webserver/CLI/routing entry chains in the generated project's own venv,
  catching files that render fine at `init` time but are missing from the
  add/remove file mapping.
- A migration test in the style of `tests/cli/test_add_service_migrations.py`
  if the service owns tables (asserts `aegis add-service <name>` bootstraps
  alembic and writes the migration file).
- Collateral: adding a service to `SERVICES` shifts the service list that
  several existing tests assert against. Expect to update
  `tests/cli/test_guided.py`, `tests/cli/test_interactive_project_selection.py`,
  `tests/cli/test_interactive_scheduler.py`, `tests/cli/test_ai_configuration.py`,
  and `tests/cli/test_scheduler_persistence.py` when they fail on counts or
  expected-option lists. These are not new files; run the gates and fix what
  goes red.

i18n:

- `aegis/i18n/locales/en.py`: add `"service.<name>"` (short description, used
  by `aegis services`) and `"projectmap.<name>"` (label used by the project map
  renderer) with the real English strings.
- `aegis/i18n/locales/{de,es,fr,ja,ko,ru,zh,zh_hant}.py`: add the SAME two keys
  to every other locale, using the English string as a placeholder. This is
  required for parity: `tests/core/test_i18n.py` asserts every locale carries
  the same keys as English and fails naming the missing key otherwise. Real
  translation of the placeholders is a separate translator-reviewed pass; do
  not attempt it here, but the keys must exist now.

Cross-cutting:

- Shared files need **no registration**. A shared file is any template path
  no component/service `FileManifest` claims; `aegis add`/`remove` finds it
  by rendering the tree at the old and new answers and diffing. Add
  `{% if include_<name> %}` conditionals to `routing.py.jinja`,
  `component_health.py.jinja`, `cards/__init__.py.jinja` — or to a brand-new
  shared file — and it is handled automatically. There is no list to add it
  to. `tests/core/test_shared_scope_completeness.py` fails, naming the file,
  if a stack-dependent file somehow ends up handled by nothing.

## Procedure

1. Write the failing tests first: `tests/services/<name>/test_<name>_service.py`
   (template side) for business logic, and `tests/api/test_<name>_endpoints.py`
   if the service exposes routes. Confirm they fail for the right reason.
2. Add `AnswerKeys.<NAME>` / `AnswerKeys.SERVICE_<NAME>` in
   `aegis/constants.py`.
3. If the service owns tables, add its `ServiceMigrationSpec` to
   `aegis/core/migration_generator.py`.
4. Add the `ServiceSpec` entry in `aegis/core/services.py`: identity fields,
   `required_components`, `pyproject_deps`, `wiring=PluginWiring(...)`,
   `migrations=[...]`, and `files=FileManifest(primary=[...])`.
5. Add the `include_<name>` question (and any config questions) to
   `copier.yml`, gating `_include_migrations` if relevant. Thread the new
   `AnswerKeys.<NAME>` through the generation/update plumbing:
   `template_generator.py`, `copier_manager.py`, `copier_updater.py`,
   `manual_updater.py`, and `commands/update.py` (see Files that change).
6. Build the template package: `app/services/<name>/`, the API router plus
   `routing.py.jinja` registration, the CLI module plus `main.py.jinja`
   registration, and the health check registration in
   `component_health.py.jinja`.
7. Wire the dashboard and frontend: card, modal, both `__init__.py.jinja`
   files, the `modal_map`/import block in `card_utils.py.jinja`, plus
   `status_overview.py.jinja`, `frontend/main.py.jinja`, and
   `system/ui.py.jinja`. If the service owns tables, also register its models
   in `database_init.py.jinja` (import + `needs_migrations` + stamp map) and
   `alembic/env.py.jinja`.
8. Gate `pyproject.toml.jinja` deps (and the shared alembic condition if the
   service owns tables).
9. Add the i18n keys `service.<name>` and `projectmap.<name>` to `en.py` with
   real strings, and stub the same two keys into every other locale for parity
   (see i18n above); `tests/core/test_i18n.py` fails otherwise.
10. Add the `tests/core/test_services.py` spec-shape + wiring tests, the
    `tests/cli/conftest.py` cache entry, and the `STACK_COMBINATIONS` /
    `everything` entries.
11. Add the service to `SERVICE_INVOCATIONS` in
    `tests/cli/test_add_service_importable.py` and, if it owns tables, add a
    migration test in the style of `test_add_service_migrations.py`. This
    verifies the add path on an EXISTING project (`aegis add-service <name>`
    against a cached base), not just fresh `aegis init` - the only way to
    catch files that render at init time but are missing from the FileManifest.
12. If any generated-project fix happened in a scratch/prototype project
    rather than directly in the template, backport it into
    `aegis/templates/` before finishing - templates are the source of truth.
13. Once the docs page exists, add `docs/services/<name>/` pages, wire them
    into the root `mkdocs.yml` nav, and set `docs_path` on the spec.
14. Run the gates below and fix anything red.

## Gates

- `make check` (lint, typecheck, test) must pass.
- `make test-stacks-quick` while iterating (fast feedback: runs the full
  validation phase against a representative subset - base, everything,
  insights).
- `make test-stacks-full` before calling the work done (runs `test-stacks`
  generation-only pass, the slow `test-stacks-build` validation pass, and
  the kitchen-sink `everything` stack across every combination).

## Pitfalls

- Template changes render from the committed git state unless you pass
  `aegis init --dev` (working tree) or commit first; testing a template edit
  with plain `aegis init` on an uncommitted change silently uses stale
  content.
- `FileManifest.primary` on the spec is the single source
  `get_component_file_mapping()` derives from (via `compute_file_mapping()`).
  A file present in the template but missing from `primary` renders
  correctly on fresh `init` (Copier just includes it) but is silently
  skipped by `add-service`/`remove-service` on an existing project - the gap
  only shows up when `tests/cli/test_add_service_importable.py` exercises
  the add path, which is why that test's `SERVICE_INVOCATIONS` list must
  include the new service.
- A file must be in **exactly one** place: either the spec's `FileManifest`
  (the service owns it outright) or nowhere (it is shared, and the
  render-diff engine handles it). Putting an owned file's path in a shared
  file's conditionals, or vice versa, is the mistake to watch for — a file
  the manifest claims is invisible to the engine by design, so a
  `{% if include_<name> %}` block inside it will never be re-rendered on
  add/remove of a *different* component.
- SQLModel model definitions (in the service's `models.py`) and the
  `ServiceMigrationSpec`'s `TableSpec` entries in `migration_generator.py`
  are two independent sources of truth for the same table; changing one
  without the other drifts the schema from the ORM model silently, since
  nothing type-checks them against each other.
- `ServiceSpec.wiring` (routers, dashboard cards/modals, deps providers) is
  metadata that currently only *mirrors* what's hand-wired into the shared
  Jinja template files - it does not yet drive their rendering for in-tree
  services. Editing one without the other leaves the spec's self-description
  (used by `aegis services`, tests, and future plugin tooling) inconsistent
  with what the generated project actually does.
- `docs_path` on the spec is pinned by `tests/core/test_spec_docs_paths.py`
  to a real file under this repo's root `/docs` - setting it before the docs
  page exists (or pointing it at the template's `docs/services/<name>/`
  instead of the root one) fails that test.
- A table-owning service needs its models registered in
  `database_init.py.jinja` (and `alembic/env.py.jinja`) on top of the
  `ServiceMigrationSpec`; if you add the migration spec but skip these, the
  service generates cleanly yet its tables are never created, and the failure
  only surfaces at runtime, not at generation.
- Threading `AnswerKeys.<NAME>` into `services.py` and `copier.yml` is not
  enough: the generate/update plumbing (`template_generator.py`,
  `copier_manager.py`, `copier_updater.py`, `manual_updater.py`,
  `commands/update.py`) also reads it, and `copier_manager.py` gates
  `needs_migration_files` on it, so a table-owning service that skips them
  breaks migrations on `aegis update` while passing a fresh `aegis init`.
- Adding an i18n key to `en.py` only fails `tests/core/test_i18n.py`, which
  requires every locale to carry the same keys; stub the key into all locales
  now and leave real translation to the separate translator pass.
- Full-body `{% if %}` gating only inside a shared file; never use Copier
  conditional filenames (breaks on Windows).
