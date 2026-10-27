---
name: plan-framework-change
description: Use before planning any change to the framework or its templates (a feature, a tool, a new convention, a refactor). Gathers what the plan must know first - the existing home for the thing, the standards it must follow, what the change touches, and the checks it must pass - so the plan reuses instead of adding a second copy.
---

# Plan a framework change

A plan made from reading files alone finds out late that a helper already
existed, that a standard (the ranges, typed figures) was skipped, or that a
test bookkeeps every tool. This skill gathers that first. The plan it produces
names the files, the existing code each change extends, the tests, and the
gates; the change itself is made by the workflow skill for its kind of work.

## When to use

Use before planning any change under `aegis/` or the templates that adds or
reshapes code: a new tool, a new convention module, a read, a component or
service change, a refactor.

Do NOT use for a typo, a docs-only change, or a change already planned with
this skill this session. Do NOT use inside a generated project; there,
`plan-with-the-twin` (shipped in the template) covers it.

## Files that change

None. This skill reads; the plan names the files. Where it looks:

- Template core: `aegis/templates/copier-aegis-project/{{ project_slug }}/app/core/`
- The live generated app: `my-app/` (its twin, its `.copier-answers.yml`)
- Ownership: `aegis/core/component_files.py`, `aegis/core/render_diff.py`
- Guards: `tests/core/` (fast), `tests/cli/test_stack_generation.py` (stacks)

## Procedure

1. **Name what the thing is** (a tool, a read, a convention module, a node
   kind, a page, a setting) and find its siblings before anything else:
   `grep -rn` the template for the same kind (`register_tool(`,
   `import_modules_named(`, `REDIS_KEYS`, `ConfigDict(frozen=True`), read one
   or two and their tests. Every sibling's home is a candidate home; a second
   copy of an existing read, model or rule is a defect in the plan.

2. **Check each standard the change touches** (table below). A change that
   alters a standard itself (moves it, adds a vocabulary, a second window
   set) is the user's call: ask before planning around it.

3. **Ask the twin what it touches**, from the live app, with template paths
   (the same check CI's Illiana job runs, before any code is written):

   ```bash
   cd my-app && uv run python -m app.cli.main patterns touches <template paths>
   cd my-app && uv run python -m app.cli.main ontology node <part ids>
   ```

   A part or dependent the plan did not expect is a stop. my-app is one
   stack: a file gated off in it (`.copier-answers.yml`) is checked in a
   scratch `scripts/generate_stack.sh everything <dir>` instead, deleted after.

4. **Find who owns each file**: `get_all_owned_paths()` (manifest-owned) or
   `get_shared_scope(paths)` (render-diff re-renders it) in
   `aegis/core/component_files.py`. A cross-cutting `{% if include_x %}` goes
   in a shared file, never one a manifest owns (template-dev).

5. **Run the pre-flight checklist** (below) and write each hit into the plan.

6. **Write the plan**: per change, the file, the existing function or model it
   extends, the failing test that comes first, and the gates. List what is
   reused, what is new, and the duplication removed on the way.

## Standards

| Standard | One home | Rule |
|---|---|---|
| Time windows | `app/core/ranges.py` (`WINDOWS`, `DAYS`, `ALL`, `since`, `start`) | A window is a day count from `WINDOWS` (`DAYS` without the `ALL` stand-in, for agents); no new window vocabulary |
| Agent-facing data | `app/core/figures.py` `FIGURES` | Frozen, `extra="forbid"` Pydantic models, sent as `model_dump(mode="json")` (a tool returns the model itself; `result_data`/`result_text` in `app/core/tools.py` read one back as JSON), never dicts or preformatted text; a field that does not apply is `absent()`, left out rather than null |
| Convention modules | `app/core/discovery.py` | Found by module name one level under `app/services/*` (`JOBS`, `tools`, `change_types`); a new name needs a `PIECES` entry in `app/services/system/service_parts.py` and rows in `docs/services/index.md`, `docs/plugins/creating.md` |
| Tools | `app/core/tools.py` `register_tool` | Every tool returns a `FIGURES` model (a refusal is `Refused`), never a dict (`returns-model`, gated), and opens its own session (an entry point); every tool declares its effect; add it to `EXPECTED_EFFECTS` in the template's `tests/core/test_tools.py`; Illiana's grant is `default_agent_config()` in `app/services/ai/domains/chat/agent_loader.py.jinja`, MCP's `MCP_TOOLS` in `app/core/config.py.jinja` |
| Aggregates | `app/core/aggregates.py` | What a service holds, for an agent: `AGGREGATES` in its `aggregates.py`, figures only (tested over every declared one), app-wide |
| Redis keys | `app/core/key_family.py`, `app/services/system/redis_keys.py` | `REDIS_KEYS` beside the writer, its module in `OWNERS` |
| Cached reads | `app/core/cache.py` `get_cache` | get, compute, `set(ttl=)`; `CACHE_ERRORS` degrade with a warning, never fail the read |
| Service layout | `app/services/system/service_parts.py` | `service.py` facade, `queries.py` reads (`reads-in-queries`), `domains/`, `adapters/`, a health check; callers import a service's `__all__`, never its `domains`; checked by `patterns check` |
| Reads hand back models | `app/services/system/service_patterns.py` (`returns-model`, gated) | A function taking a session, and every registered tool, returns a typed model (`FIGURES` where an agent, the API or Overseer reads it, a health check's metadata included), never `dict[str, Any]`, a bare `dict`, `list[dict[str, Any]]` or `Any`; a label's counts may stay `dict[str, int]`. A read with no session (a vector store, a file) follows the same rule though the check cannot see it |
| Service functions | `app/services/system/service_patterns.py`, `async_patterns.py` | Takes its session as a required parameter and opens none (`takes-session`, gated; `jobs.py`/`health.py` open the one); blocking work off the loop (gated) |
| Charts | `app/services/ai/domains/chat/cards.py` | Bar and pie rows are `{label, value}`; money is integer cents |
| Twin nodes | `app/core/ontology/model.py`, `app/services/system/staged_paths.py` | A new kind joins `Kind` and the `Node` union; what the map draws is `PLACED` and `registry_of` |
| Map and chip styling | `app/components/web_frontend/templates/components/macros/` | Reuse a macro (`facts`, `stat_row`); every public macro has a catalog example |

Paths in the table are under `aegis/templates/copier-aegis-project/{{ project_slug }}/`
unless they start with `docs/`.

## Pre-flight checklist

- **Size**: `wc -l` each file the plan grows against 500 (logic) or 900
  (declarations) and its `BUDGET` entry in `tests/core/test_module_size_budget.py`;
  a file near the cap gets a new module, not more lines.
- **Dual-write**: each changed file lands in the template and in `my-app/`
  (`.py` copied, `.jinja` edited by hand).
- **i18n**: new user-facing text gets keys in `en.py`, stubbed into every
  other locale (the i18n skill).
- **New part or answer**: prompt scripts shift (`tests/cli/test_guided.py` and
  siblings), the stack goes in `.github/workflows/stack-matrix.yml`, and
  `make parts` and `make readme` regenerate.
- **New file in a part**: no touched-file run selects that part's
  `tests/services/test_<part>_module_layout.py` or `test_service_parts.py`;
  name them in the plan, and run `patterns check --strict <app paths>` in
  `my-app/` (a read beside an existing one still belongs in `queries.py`;
  my-app has no baseline, so read the changed files' own findings).
- **Agent reach**: a new read an agent should use is granted (agent tools,
  `MCP_TOOLS`) and named where the agent looks (the prompt's map,
  `app/core/ontology/summary.py`); an agent does not use what it is not told.
- **Backends**: anything per worker, scheduler or database backend is checked
  on each (`scripts/generate_stack.sh` or `aegis init --dev -c ...`), from a
  shell with Redis unreachable when a shell runs it.

## Gates

- The fast guards for what changed, before generating anything:
  `uv run pytest tests/core/test_template_tree_hygiene.py
  tests/core/test_shared_scope_completeness.py
  tests/core/test_render_diff_transition_coverage.py
  tests/core/test_module_size_budget.py`, and the template's own tests for
  what changed (its `tests/core/test_tools.py` for a tool) run in `my-app/`.
- `patterns check --strict <changed app paths>` in `my-app/` (or the scratch
  stack that has them) once the code is written: the same rules Illiana
  gates in CI, so a dict-returning read or a self-opened session is caught
  here, not on the PR.
- `uv run pytest tests/core` and the generated app's `tests/test_saved_settings.py`
  before push.
- `make test-stacks-quick` for a cross-cutting template change; CI runs the
  full matrix and the Illiana check.
- Once the change is built, before offering a commit or pull request: the
  `dry` skill on the branch's diff (reuse, simplification, efficiency,
  altitude), its fixes applied and the gates above run again. Never offer
  the commit first.

## Pitfalls

- `import_modules_named` walks one level: a module at
  `app/services/<svc>/domains/<x>/<name>.py` is never found, so it must be
  imported from the service's top-level convention module.
- `app/services/system/tools.py` is near the size cap, so a new tool's
  function lives in its own module and only its `register_tool` line goes there.
- A standard kept in `web_frontend` cannot be imported by a service or core
  module, so a backend reader of it means moving it to `app/core` first.
- The twin in `my-app/` sees only what that stack generated, so a file gated
  off there reports nothing, which reads as "touches nothing".
- A plan that grants an agent a tool without naming it in the agent's map
  leaves the agent guessing ids, as it did with the worker queues.
