---
name: template-dev
description: Use when developing or modifying Copier templates in aegis/templates, or backporting a change from a generated project (e.g. a prototype scratch project) back into the templates. Covers the two development workflows, the three rendering modes that resolve where Copier reads template content from, and the template-specific gotchas that silently break generation or update.
---

# Template dev

Develops and backports changes to the Copier templates that every generated
Aegis Stack project is rendered from. This is the general template-editing
workflow: how to iterate, how rendering picks up (or ignores) your edits, and
the traps that only show up on `aegis update`, not on a fresh `aegis init`.

## When to use

Use when the task touches template content directly (`docker-compose.yml.jinja`,
`Makefile.jinja`, any file under `app/`, `pyproject.toml.jinja`, `copier.yml`,
etc.) or when a fix was made inside a generated project and needs to be
carried back into the templates.

Do NOT use this skill for adding a brand-new component or service (a
`ComponentSpec`/`ServiceSpec` entry, its `FileManifest`, and its
generation/update plumbing) - use the `add-component` or `add-service` skill
instead; they cover the plugin-spec registry work this skill assumes is
already done. Do NOT use for ordinary feature work inside the CLI tool itself
(`aegis/commands/`, `aegis/core/` logic unrelated to rendering) unless that
work is specifically about how templates render or update.

## Files that change

Source-of-truth law: templates ship, generated projects are prototypes. The
templates live under:

- `aegis/templates/copier-aegis-project/{{ project_slug }}/`: every file a
  generated project contains, one-to-one. A plain file with no Jinja logic
  ships as-is (e.g. `app/components/worker/registry.py`); a file with
  conditional content ships with a `.jinja` suffix (e.g.
  `app/components/worker/events.py.jinja`).
- `copier.yml` (repo root, not under `templates/`): the question set Copier
  prompts for or reads answers from.
- `aegis/templates/copier-aegis-project/{{ project_slug }}/.copier-answers.yml.jinja`:
  the answers file template; see Pitfalls for which fields belong here.
- `aegis/core/copier_manager.py`: renders a new project (`aegis init`),
  including the dev-mode/git-mode source selection and the post-generation
  answers backfill.
- `aegis/core/copier_updater.py`: resolves the template source and version
  ref for `aegis update`.
- `aegis/core/manual_updater.py`: adds/removes a single component or service
  on an existing project without a full Copier update.
- `aegis/core/render_diff.py`: the engine `manual_updater` uses to decide
  what a shared file needs on add/remove. Reads the file's policy
  annotation; you rarely edit this, but its module docstring is the
  reference for the decision table below.
- `Makefile` (repo root): the `test-template*` and `test-stacks*` targets used
  to validate template changes.

Backport target mapping: any file you edit inside a generated project at
`<project>/<path>` has its template source at
`aegis/templates/copier-aegis-project/{{ project_slug }}/<path>` (or
`<path>.jinja` if that file needs Jinja conditionals). Backport with:

```bash
cp my-app/app/components/worker/registry.py \
  "aegis/templates/copier-aegis-project/{{ project_slug }}/app/components/worker/registry.py"
```

Quote the destination path; the directory name contains the literal `{{ project_slug }}`
placeholder, which a shell would otherwise try to expand.

## Who owns a template file

Every file in the tree is governed by exactly one mechanism, and which one
is **derived, not declared** — there is no registration list. Adding a new
template file requires no bookkeeping anywhere.

- **Component/service-owned** — the path appears in some spec's
  `FileManifest` (`aegis/core/components.py` / `services.py`). Its existence
  is decided by manifest membership: `aegis add` copies it, `aegis remove`
  deletes it. Most of a component's own files.
- **Shared** — nothing claims it. On add/remove the render-diff engine
  renders the tree at the old answers and the new answers and diffs; a file
  whose output changed gets written. This is where `{% if include_x %}`
  conditionals belong.

Consequence worth internalising: a `{% if include_worker %}` block inside a
file the *auth* manifest owns will never re-render when worker is added,
because owned files are invisible to the engine by design. Cross-cutting
conditionals go in shared files.

### Per-file policy annotations

A shared file can override the default handling with a comment on its very
first line, read and stripped before rendering:

```jinja
{#- aegis: user-owned -#}        create once, then never touch (README, docs/)
{#- aegis: warn-if-diverged -#}  overwrite while pristine, else preserve + report
{#- aegis: no-backup -#}         overwrite without writing a .backup
```

No annotation means the default: overwrite while pristine (with a
`.backup`), 3-way merge once the user has edited it.

The `-#` / `#-` trim markers are **required**, not stylistic. `aegis init`
and `aegis update` render through Copier, which knows nothing about these
annotations; without the trim markers the comment leaves a blank line at
the top of every generated file. A recognised word missing its markers
raises rather than silently degrading.

### Whole-file gates leave a stub

`{%- if include_x -%}...{%- endif -%}` wrapping an entire file still emits a
newline when the gate is off, so Copier writes a 1-byte file. That stub is
what the template currently produces, so it counts as pristine and gets
populated when the gate flips on. Don't "tidy" it by making the engine treat
existing-but-empty as user content — that is the exact bug that once left
`docker-compose.prod.yml` empty forever after `aegis add ingress`.

## Procedure

Pick one of two workflows, then apply the rendering mode that matches it.

**Template-first** (the change is already known):

1. Edit the file(s) directly under
   `aegis/templates/copier-aegis-project/{{ project_slug }}/...`.
2. Generate a test project with `aegis init test-project --dev` (working
   tree, no commit needed) or `make test-template-quick`/`make test-template`
   (committed state, see rendering modes below).
3. Verify the generated project behaves as expected.
4. Clean up with `make clean-test-projects`.

**Prototype-first** (exploratory, the fix is easier to find by iterating
directly on generated code):

1. Generate a test project (`aegis init <name> --dev`, or any
   `make test-template*` target).
2. Iterate directly in the generated project until it works.
3. Backport immediately, in the same session, using the `cp` pattern above
   for every file you touched. Do not defer this; changes left only in a
   generated project are lost on the next `aegis init`.
4. Regenerate a fresh project from the templates to confirm the backport is
   correct, then clean up.

Rendering modes (this resolves which template content Copier actually reads):

- Default (installed package, or local git repo without `--dev`): Copier
  renders the COMMITTED git state, either via a GitHub URL (pip/uvx install)
  or a `git+file://` URL pointing at the local repo (`aegis/core/copier_manager.py`,
  the `is_git_repo(template_root)` branch). Uncommitted template edits are
  invisible even though the files look changed locally.
- `aegis init --dev`: renders the WORKING TREE. `aegis/core/copier_manager.py`'s
  `dev_mode` branch copies `copier.yml` and
  `aegis/templates/copier-aegis-project` from the working tree into a
  temporary directory and generates from that plain path, so uncommitted
  edits show up immediately. Use this for local iteration; no commit
  required. Projects generated this way have no `_commit` pin and cannot run
  `aegis update` later.
- External project update: `aegis update -y -p <project> -t <aegis-stack repo> --to-version HEAD`.
  `-p`/`--project-path` points at the target project, `-t`/`--template-path`
  points Copier at a local aegis-stack checkout instead of the installed
  package, and `--to-version HEAD` resolves to the latest commit on the
  current branch instead of a version tag. This still reads the COMMITTED
  state of that checkout, not its working tree, so template changes must be
  committed first.

## Gates

Start with the fast ones. These run in under a second against rendered
output and catch the two mistakes template edits actually make:

- `uv run pytest tests/core/test_template_tree_hygiene.py` — every template
  parses, and no file is shadowed by a `.jinja` twin.
- `uv run pytest tests/core/test_shared_scope_completeness.py
  tests/core/test_render_diff_transition_coverage.py` — a new
  stack-dependent file is handled by something, and every add/remove
  transition writes the files it needs.

Run those *before* generating a project; a template that fails to parse
wastes a 40-second `aegis init` to tell you so.

Then the generation gates:

- `make test-template` after any template edit (generates a project and runs
  its full validation, including `make check` inside the generated project).
- Whichever narrower target matches the touched component or service, for
  faster iteration: `make test-template-quick` (no validation),
  `make test-template-with-components`, `make test-template-auth`,
  `make test-template-worker`, `make test-template-database`,
  `make test-template-full`, `make test-template-ai`,
  `make test-template-ai-memory`, `make test-template-ai-sqlite`.
- `make test-stacks-quick` while iterating on a cross-cutting template change
  (fast feedback against a representative subset: base, everything, insights).
- `make test-stacks-full` before calling multi-component template work done
  (generation-only pass, the slow build/validation pass, and the kitchen-sink
  `everything` stack).
- `make check` for any non-template Python change made along the way (for
  example, editing `copier_manager.py` or `manual_updater.py`).
- `make clean-test-projects` to remove generated test project directories
  once verification is done.

## Pitfalls

- Gate conditional content with a full-body `{% if %}...{% endif %}` wrap
  only. Never use Copier conditional filenames; that convention broke on
  Windows and is banned outright.
- Carry no inline comments in `docker-compose.yml.jinja` or its `.dev`/`.prod`
  variants. Which components a given project selects varies per stack, so a
  comment written for one combination misleads for another; state conditions
  through the Jinja gate itself.
- Every new `copier.yml` question needs a matching line in
  `.copier-answers.yml.jinja`, except fields gated by a `when:` clause.
  Copier itself drops `when`-gated answers from the rendered answers file
  (observed for `worker_backend`, `scheduler_backend`, `include_oauth`), so
  the actual persistence path for those is `copier_manager.py`'s
  post-generation backfill loop, which patches any `copier_data` key Copier
  dropped directly into the written `.copier-answers.yml`. Adding a
  `when`-gated field to the `.jinja` list anyway is harmless but is not what
  makes it survive.
- `copier` is pinned below 9.15 in `pyproject.toml` (9.15+ relocates
  `.copier-answers.yml` out of the generated project directory, breaking
  `aegis update`). A dependabot ignore rule blocks upgrade PRs past that
  ceiling; do not bump the pin even if a bot proposes it.
- `uv.lock` hides fresh-install dependency drift. Validate a template
  dependency change (new `pyproject.toml.jinja` gates, new packages) with
  `uvx` or a fresh `uv sync` inside a freshly generated project, not the
  locally locked dev environment, since the lock file can mask a resolution
  that only fails on a clean install.
