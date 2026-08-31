---
name: add-component
description: Use when adding a new infrastructure component (worker, scheduler, database, redis, ingress, observability) to the Aegis Stack framework itself, or adding a new variant axis (like worker_backend or database_engine) to an existing component. Covers the plugin-spec registry, dependency resolution, copier questions, generation/update plumbing, template, test, docs, and i18n files that must change together.
---

# Add component

Adds a new infrastructure component (background worker, scheduler, database,
redis, ingress, observability) to the framework so generated projects can
select it via `aegis init` or add it later via `aegis add`, OR adds a new
variant axis to an existing component (a second/third backend choice like
`worker_backend` on `worker` or `database_engine` on `database`). Traced from
`worker` (with its `worker_backend` axis: arq/dramatiq/taskiq) and `database`
(with its `database_engine` axis: sqlite/postgres).

## When to use

Use for either:

- A brand-new optional component (infrastructure, not business logic) behind
  its own `include_<name>` copier question, addable/removable via
  `aegis add` / `aegis remove`.
- A new variant axis on an existing component: a second copier question
  (`<component>_<axis>`) that changes which files render for that component,
  following the `worker_backend` / `database_engine` pattern.

Do NOT use for adding a **service** (business logic: auth, AI, blog,
finance, payment, comms, insights) - services live in
`aegis/core/services.py` and share the same `PluginSpec` shape but a
different file footprint and CLI surface (`aegis add-service`, not
`aegis add`); use the `add-service` skill instead. Do NOT use for changing
behavior inside an existing component with no new question or file gating;
that is ordinary feature work.

## Files that change

Registry (`ComponentSpec` is a thin alias of `PluginSpec` pinned to
`kind=COMPONENT`; see `aegis/core/plugins/spec.py`):

- `aegis/core/components.py`: add a `ComponentSpec` entry to the `COMPONENTS`
  dict. Set `type` (`ComponentType.INFRASTRUCTURE`; `ComponentType.CORE` is
  reserved for `backend`/`frontend` in `CORE_COMPONENTS` - core components are
  never prompted, never removable, and skipped by cleanup entirely),
  `description`/`long_description`, `required_components` (hard deps, e.g.
  worker requires `["redis"]`), `recommended_components`, `pyproject_deps`,
  `docker_services` (compose service names this component owns, used by
  stack-generation tests), `template_files` (display list), `marker_path`
  (the path used to detect the component on disk - for `reconcile_answers_from_disk`
  and dev-mode cleanup context), `docs_path` (see docs section below), and
  `migrations=[...]` only if the component owns tables (see `SCHEDULER_MIGRATION`
  in `aegis/core/migration_generator.py` for the pattern: a schema-qualified
  table, generated only for non-memory/non-sqlite backends).
- `aegis/core/components.py`: `files=FileManifest(primary=[...], extras={...})`
  - every path the component owns. `primary` is the always-on add/init base;
  `aegis/core/post_gen_tasks.py`'s `get_component_file_mapping()` derives
  from every spec's manifest via `compute_file_mapping()` (`aegis/core/file_manifest.py`),
  so there is no separate hand-maintained mapping to edit. Use `extras` for
  file groups that only render real content for a specific variant value
  (e.g. scheduler's `"scheduler_persistence"` group, gated on
  `scheduler_backend != "memory"`) - keeping them out of `primary` stops
  `aegis add` from writing 0-byte stubs when the parent variant doesn't need
  them; `aegis remove` still deletes them via `get_component_files(..., full=True)`.
- `aegis/constants.py`: `ComponentNames` - add `<NAME> = "<name>"` and append
  it to `INFRASTRUCTURE_ORDER` (controls interactive prompt ordering).
  `AnswerKeys` - add `<NAME> = "include_<name>"`. For a new variant axis, add
  the axis key (e.g. `<COMPONENT>_<AXIS> = "<component>_<axis>"`) and, if the
  axis has a fixed enum of values, a dedicated `<Axis>Backends`/`<Axis>Type`
  class near `WorkerBackends` / `StorageBackends` with an `ALL` list.
- `aegis/core/dependency_resolver.py`: no edits needed for a plain component -
  it reads `ComponentSpec.requires`/`.recommends`/`.conflicts` generically via
  `COMPONENTS`. Only add logic here if the new component needs a resolution
  rule beyond simple hard-dependency (worker -> redis is handled by
  `required_components` alone, no custom code).
- `copier.yml` (repo root, not under `templates/`): add the `include_<name>`
  bool question. For a variant axis, add `<component>_<axis>` with
  `choices:` and `when: "{{ include_<component> }}"` - UNLESS the value must
  survive even when the component is off (compare `database_engine`, which
  has **no** `when` clause because templates gate on it regardless of
  `include_database`, e.g. a persistent scheduler needs to know the engine
  before database is even selected).
- `aegis/templates/copier-aegis-project/{{ project_slug }}/.copier-answers.yml.jinja`:
  add `include_<name>: {{ include_<name> }}`. For an axis gated by `when`,
  adding the line here is NOT required for correctness - Copier omits
  `when`-gated fields from the rendered answers file (observed for
  `worker_backend`, `scheduler_backend`, `include_oauth`; none of them
  appear in this file today), and `copier_manager.py`'s post-generation
  patch (below) backfills every `copier_data` key Copier dropped. Add the
  line anyway for axes that are NOT `when`-gated (like `database_engine`,
  which IS listed here) since those are the ones templates read
  unconditionally.

Generation and update plumbing (thread the new `AnswerKeys.<NAME>` /
`AnswerKeys.<COMPONENT>_<AXIS>` answer key through every one of these; a
component that skips them generates fine at `aegis init` but breaks
`aegis add`/`aegis remove`/`aegis update` on an existing project):

- `aegis/core/template_generator.py` (`TemplateGenerator.__init__` and
  `get_template_context()`): extract the axis value from bracket syntax
  (`worker[dramatiq]`) the same way `self.worker_backend` is derived from
  `extract_engine_info(component)`, default it (`WorkerBackends.ARQ`), and
  add it to the returned context dict. Also branch in the pyproject-deps
  loop (`base_name == ComponentNames.WORKER` block) if different variant
  values pull different pip packages.
- `aegis/core/copier_manager.py` (`generate_with_copier`): add
  `AnswerKeys.<NAME>: template_context[AnswerKeys.<NAME>] == "yes"` (or
  `.get(..., default)` for optional flags) to the `copier_data` dict passed
  to `run_copy`. This is also where the backfill described above lives -
  every non-underscore `copier_data` key gets written into
  `.copier-answers.yml` after generation if Copier dropped it, so this dict
  is the actual source of truth for what ends up in the answers file, not
  the `.copier-answers.yml.jinja` list.
- `aegis/core/manual_updater.py` (`ManualUpdater`): `get_copier_defaults()`
  (from `aegis/core/component_files.py`) merges copier.yml defaults under
  the persisted answers at construction time, so a variant axis with a
  `default:` in copier.yml needs no extra wiring here for the *default*
  case. But `add_component`/`remove_component` must reference
  `AnswerKeys.<COMPONENT>_<AXIS>` explicitly anywhere the render context
  needs it - as of this trace, `manual_updater.py` has **zero** references
  to `worker_backend`, which is why `aegis add worker[dramatiq]` on an
  existing project silently ignores the bracket and always adds arq (the
  default). Don't repeat this gap for a new axis: thread it through
  `add_component`'s context building, mirroring how `aegis/commands/add.py`
  threads `AnswerKeys.DATABASE_ENGINE`/`AnswerKeys.SCHEDULER_BACKEND` into
  `component_data` before calling `updater.add_component(component, component_data)`.
- `aegis/commands/add.py` (`add_command`): parse the variant out of bracket
  syntax via `extract_engine_info(comp)` for the new component (mirrors the
  scheduler-backend block), validate it against the axis's `ALL` list, and
  populate `update_data[AnswerKeys.<COMPONENT>_<AXIS>]` / the per-component
  `component_data` dict passed to `updater.add_component(...)`.
- `aegis/commands/update.py`: no per-component AnswerKeys threading exists
  here today (verify this still holds before skipping it) - `aegis update`
  runs the full Copier update flow and re-derives context from the project's
  own (reconciled) answers file, not from a hand-maintained key list.
- `aegis/cli/guided.py` / `aegis/cli/interactive.py`: add a
  `choose_<component>_backend(self) -> str` method (on the guided-setup UI
  class) following `choose_worker_backend()` / `choose_database_engine()` -
  a list of `_Choice(value, label, description)` tuples fed to `self._select(...)`
  with an i18n-backed prompt string (`_g("prompt.<component>_backend", "...")`)
  and per-choice description keys (`choice.<component>.<value>`).

Template side (`aegis/templates/copier-aegis-project/{{ project_slug }}/`):

- `app/components/<name>/`: the component's own package.
- `docker-compose.yml.jinja` / `.dev` / `.prod`: gate services behind
  `{%- if include_<name> %}` (full-body wrap, never a Jinja expression
  inside a YAML value Copier can't parse standalone). These compose
  templates carry **no inline comments** - which components a given
  project selects varies per stack, so a comment written for one
  combination misleads for another; state conditions through the Jinja
  gate itself, not prose beside it.
- `Makefile.jinja`: gate any new `make` targets the component needs
  (compare how `worker`/`scheduler` targets are conditioned).
- `app/components/backend/startup/component_health.py.jinja`: register the
  health check behind `{%- if include_<name> %}`, following the existing
  `include_worker` / `include_database` blocks. For a variant axis, nest a
  second `{%- if <component>_<axis> == "value" %}` inside.
- `pyproject.toml.jinja`: gate the component's `pyproject_deps` behind
  `{%- if include_<name> %}`. For a variant axis with per-value deps (arq
  vs dramatiq vs taskiq each pull different packages), branch on the axis
  value inside that same gate.
- `docs/components/<name>/index.md` (+ `configuration.md`, `examples.md`,
  `extras/<topic>.md` as applicable - this is the multi-page convention
  `worker` and `scheduler` use; a single `docs/components/<name>.md` file
  also satisfies the docs_path test, matching `database`/`scheduler`'s
  top-level file). Wire the new pages into the root `mkdocs.yml` nav under
  the `Components:` block.
- Tests (generated-project template tests): `tests/components/test_<name>.py`,
  and API/frontend tests if the component ships routes or dashboard
  cards/modals (`app/components/frontend/dashboard/cards/<name>_card.py`,
  `modals/<name>_modal.py`, exported from the matching `__init__.py.jinja`
  files, same wiring shape as the service card/modal pattern in `add-service`).

Cross-cutting:

- Shared files need **no registration**. A shared file is any template path
  no component/service `FileManifest` claims; `aegis add`/`remove` finds it
  by rendering the tree at the old and new answers and diffing. Put
  `{% if include_<name> %}` conditionals in `docker-compose.yml`,
  `pyproject.toml`, `Makefile`, `component_health.py`, `app/core/config.py`,
  `.env.example` — or in a brand-new shared file — and it is handled
  automatically. There is no list to add it to.
  - If the component needs a whole file of its own, put it in the spec's
    `FileManifest` instead (see "Files this component owns" above). That is
    the only file declaration there is.
  - `tests/core/test_shared_scope_completeness.py` fails, naming the file,
    if a stack-dependent file somehow ends up handled by nothing.
- `docs/components/<name>/index.md` (or `<name>.md`) is pinned by
  `tests/core/test_spec_docs_paths.py` once `docs_path` is set on the spec
  - it accepts either `docs/<docs_path>.md` or `docs/<docs_path>/index.md`.
  Leave `docs_path=""` until the page exists.

i18n:

- `aegis/i18n/locales/en.py`: add `"component.<name>"` (short description,
  shown by `aegis add --help` component listings and the guided setup) and
  `"component.<name>.long"` (long-form description) with real English
  strings. For a variant axis, also add `"prompt.<component>_<axis>"` and
  one `"choice.<component>.<value>"` key per choice (see
  `choice.worker.arq` / `choice.worker.dramatiq` / `choice.worker.taskiq`).
- `aegis/i18n/locales/{de,es,fr,ja,ko,ru,zh,zh_hant}.py`: add the SAME keys
  to every other locale, using the English string as a placeholder. This is
  required for parity: `tests/core/test_i18n.py` asserts every locale
  carries the same keys as English (one `test_<locale>_has_all_keys` per
  locale) and fails naming the missing key otherwise. Real translation is a
  separate translator-reviewed pass; do not attempt it here, but the keys
  must exist now.

Tests (this repo's own CLI/core test suite):

- `tests/cli/test_stack_generation.py`: add a `StackCombination` entry to
  `STACK_COMBINATIONS` (mirrors the `worker`/`scheduler`/`full` entries) with
  `expected_files`, `expected_docker_services`, and `expected_pyproject_deps`.
- `tests/cli/conftest.py`: add a `<name>_with_<variant>` entry to
  `NAMED_PROJECT_SPECS` for each new variant value (see
  `base_with_worker_taskiq` / `base_with_worker_dramatiq`) so downstream
  tests copy a cached project instead of regenerating one.
- `tests/cli/test_add_command.py`: add coverage for `aegis add <name>` (and,
  if applicable, `aegis add <name>[<variant>]`) following the existing
  `test_add_scheduler_with_backend_flag_sqlite` / `test_add_worker_auto_adds_redis`
  style. There is no dedicated "importable regen guard" test for components
  analogous to `add-service`'s `SERVICE_INVOCATIONS` - add explicit add-path
  assertions here instead so a missing `FileManifest` entry surfaces as a
  test failure rather than a stub file in the wild.
- `tests/core/test_spec_docs_paths.py` and `tests/core/test_i18n.py` need no
  edits - they parametrize over `COMPONENTS`/`SERVICES` and the locale
  catalogs automatically; they just need to pass.

## Procedure

1. Write the failing test first: add a `StackCombination` to
   `tests/cli/test_stack_generation.py::STACK_COMBINATIONS` asserting the
   new component's expected files/docker services/deps. Confirm it fails
   for the right reason (component doesn't exist yet).
2. Add `ComponentNames.<NAME>` (+ `INFRASTRUCTURE_ORDER` entry) and
   `AnswerKeys.<NAME>` in `aegis/constants.py`. For a variant axis, add the
   axis key and its `<Axis>Backends`-style enum class.
3. Add the `ComponentSpec` entry in `aegis/core/components.py`: identity
   fields, `required_components`, `pyproject_deps`, `docker_services`,
   `marker_path`, `files=FileManifest(primary=[...], extras={...})`, and
   `migrations=[...]` if it owns tables.
4. Add the `include_<name>` question to `copier.yml` (and the axis question
   with `choices`/`when` if applicable). Add the corresponding line to
   `.copier-answers.yml.jinja` for any NOT-`when`-gated field; `when`-gated
   fields are backfilled automatically (see Files that change).
5. Thread the new answer key(s) through the generation/update plumbing:
   `template_generator.py`, `copier_manager.py`, `manual_updater.py`,
   `aegis/commands/add.py` (bracket parsing + `component_data`), and the
   guided/interactive prompt classes (`guided.py`/`interactive.py`).
6. Build the template package: `app/components/<name>/`, docker-compose
   gating (no inline comments), `Makefile.jinja` targets, `pyproject.toml.jinja`
   deps, and the health check registration in `component_health.py.jinja`.
7. If the component ships dashboard UI, wire the card/modal and their
   `__init__.py.jinja` exports (mirror the service pattern in `add-service`).
8. Add the i18n keys (`component.<name>`, `component.<name>.long`, plus
   `prompt.<component>_<axis>` / `choice.<component>.<value>` for a variant
   axis) to `en.py`, then stub the same keys into every other locale for
   parity; `tests/core/test_i18n.py` fails otherwise.
9. Add the `tests/cli/test_stack_generation.py` combination (from step 1,
   now passing), the `tests/cli/conftest.py` cache entries per variant, and
   `tests/cli/test_add_command.py` add-path coverage.
10. If any generated-project fix happened in a scratch/prototype project
    rather than directly in the template, backport it into
    `aegis/templates/` before finishing - templates are the source of truth.
11. Once the docs page exists, add `docs/components/<name>/` (or
    `<name>.md`), wire it into the root `mkdocs.yml` nav, and set
    `docs_path` on the spec.
12. Run the gates below and fix anything red.

## Gates

- `make check` (lint, typecheck, test) must pass.
- `make test-stacks-quick` while iterating (fast feedback: runs the stack
  validation phase against a representative subset - base, everything,
  insights).
- `make test-stacks-full` before calling the work done (runs the
  generation-only `test-stacks` pass, the slow `test-stacks-build`
  validation pass, and the kitchen-sink `everything` stack).

## Pitfalls

- Template changes render from the committed git state unless you pass
  `aegis init --dev` (working tree) or commit first; testing a template
  edit with plain `aegis init` on an uncommitted change silently uses stale
  content.
- Copier conditional filenames are banned (broke on Windows); gate content
  with a full-body `{% if %}...{% endif %}` wrap inside the file instead of
  naming the file conditionally.
- `copier` is pinned below 9.15 in `pyproject.toml` (9.15+ relocates
  `.copier-answers.yml`, breaking `aegis update`); a dependabot ignore rule
  guards the pin - do not "fix"/bump it even if a bot PR proposes it.
- `.copier-answers.yml.jinja` looks incomplete on purpose: fields gated by a
  copier.yml `when:` clause (like `worker_backend`, `scheduler_backend`,
  `include_oauth`) are omitted from it, because Copier itself drops
  conditional answers on render. Don't "fix" this by adding them - the
  actual persistence path is `copier_manager.py`'s post-generation backfill,
  which patches any `copier_data` key Copier dropped directly into the
  written `.copier-answers.yml`.
- `FileManifest.primary` on the spec is the single source
  `get_component_file_mapping()` derives from. A file present in the
  template but missing from `primary` renders correctly on fresh `init`
  (Copier just includes it) but is silently skipped by `aegis add`/`aegis
  remove` on an existing project - there is no equivalent to `add-service`'s
  `SERVICE_INVOCATIONS` regen-gap guard for components today, so cover this
  with explicit `tests/cli/test_add_command.py` assertions instead.
- The worker backend suffix-rename in `post_gen_tasks.cleanup_components`
  (`_rename_backend_files` / `_remove_backend_files`) is the concrete model
  for a variant axis that ships parallel source files
  (`registry_dramatiq.py`, `registry_taskiq.py`, canonical `registry.py`):
  at generation time it renames the chosen backend's `*_<backend>.py` files
  to their canonical names and deletes the other backends' files. Skipping
  this for a new axis leaves all variants' files on disk simultaneously,
  each importing modules that shadow each other.
- The same function distinguishes **init** (backend-specific source files
  still present, e.g. `*_dramatiq.py`) from **update** (only canonical
  files remain from a prior run) by checking whether any `*_<backend>.py`
  files exist before renaming. Running the arq-cleanup unconditionally on
  update would delete the canonical files a previous run already renamed
  into place, which is the exact bug the init-vs-update branch exists to
  prevent; a new variant axis must preserve it.
- `aegis/commands/manual_updater.py`'s `add_component` has **no** knowledge
  of `worker_backend` today: `aegis add worker[dramatiq]` on an existing
  project always installs the arq default, silently discarding the bracket
  value. Don't assume bracket syntax "just works" for a new axis on the add
  path - verify (and if needed, add) the threading in `add.py` and
  `manual_updater.py` explicitly; it is not inherited for free from the
  `aegis init` path.
- `docs_path` on the spec is pinned by `tests/core/test_spec_docs_paths.py`
  to a real file under this repo's root `/docs` (either `docs/<path>.md` or
  `docs/<path>/index.md`) - setting it before the docs page exists fails
  that test.
- New i18n keys get real strings in `aegis/i18n/locales/en.py` and the same
  keys with English-placeholder values in every other locale in the same
  change (required for `tests/core/test_i18n.py` parity); real translation is
  left to a separate translator-reviewed pass.
- A component that owns tables (like scheduler's Postgres-only execution
  history) generates its migration only when the chosen backend needs
  persistence - model the `scheduler_backend != "memory"` gating in
  `get_services_needing_migrations` and the `needs_migrations` set in
  `post_gen_tasks.cleanup_components`; forgetting either leaves `alembic/`
  either missing when needed or present with no matching migration.
