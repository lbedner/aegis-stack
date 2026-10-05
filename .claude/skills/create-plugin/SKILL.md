---
name: create-plugin
description: Use when building an Aegis Stack plugin, a separate package (aegis-stack-<name>) that renders files into a project through `aegis add <name>`. Covers the scaffold, the plugin spec, the file conventions a project finds on disk, testing inside a generated project, and publishing.
---

# Create plugin

A plugin is a separate Python package whose `get_spec()` returns a `PluginSpec`
(the same declaration built-in services use) and whose templates render into a
project on `aegis add <name>`. Much of what a plugin contributes needs no
wiring: the project finds a module of a known name in every service package on
disk.

## When to use

Use when the work is a new optional capability shipped outside this repo: an
integration (a source for the research service, a scraper), or a service a
project opts into by installing a package.

Do NOT use for a capability that ships with the framework itself (use the
`add-service` or `add-component` skill), or for changing the plugin system in
this repo (that is ordinary work in `aegis/core/plugins/`).

## Files that change

In the plugin repository (created by `aegis plugins create <name>`):

- `pyproject.toml`: the `aegis.plugins` entry point, keywords
  (`aegis-stack-plugin` lists it in the directory), the `aegis-stack` floor.
- `src/aegis_stack_<name>/plugin.py`: `get_spec()`: `required_services` /
  `required_components`, `files=FileManifest(primary=[...])`, `wiring=` only
  for what a convention module does not cover, `migrations=` only if it owns
  tables.
- `src/aegis_stack_<name>/templates/{{ project_slug }}/`: the files a project
  receives. Convention modules in `app/services/<service>/`:
  - `models.py` (or `models/`): tables, picked up by the model registry.
  - `change_types.py`: changes a model proposes and a user approves.
  - `scheduled_jobs.py`: `JOBS`, a tuple of `ServiceJob` (`app.core.schedule`).
  - `tools.py`: `register_tool(...)` calls (`app.core.tools`), for agents and
    MCP clients.
  - `sources.py`: `register_source(...)` (`app.services.research.registry`),
    for a research source.
- `src/aegis_stack_<name>/templates/{{ project_slug }}/tests/`: the template's
  tests, which run inside a generated project.
- `tests/test_plugin.py`: tests that pin the spec.
- `README.md`, `LICENSE`.

In this repo, only when a plugin needs a hook no convention covers: the
convention's discovery in the template (`app/core/discovery.py`
`import_modules_named`) and `docs/plugins/creating.md`'s convention table.

## Procedure

1. Scaffold: `aegis plugins create <name> -d <parent> --author "..." --description "..."`.
2. Pick the convention modules the plugin needs; prefer them over `wiring=`,
   which a project only honours for the hooks `PluginWiring` declares.
3. Record real third-party responses as fixtures under the template's
   `tests/fixtures/<name>/` before writing any mapping code; build the model
   from what the API actually returns.
4. Write the template's failing tests first (against the fixtures, with an
   `httpx.MockTransport` or a module-level `_transport` seam, never the
   network).
5. Write the template modules and declare every owned path in
   `files=FileManifest(primary=[...])`.
6. Install the plugin into the aegis environment that renders it:
   `uv pip install -e <plugin>`; confirm with `aegis plugins list`.
7. Generate a project without the plugin's dependencies, run
   `aegis add <name>`, and run the template's tests there under the project's
   gate: `uv run pytest <tests> --queryspy-strict --queryspy-baseline .queryspy-baseline.json`.
8. Run the plugin for real against the live service once, through the
   project's CLI or API.
9. Copy back anything the project's `make fix` reformatted in the rendered
   files, so the template matches what a project receives.
10. In the plugin repo, `make check`; then create the repository with the
    `aegis-stack-plugin` topic and push. Publishing to PyPI is the separate step
    in `docs/plugins/publishing.md`.

## Gates

- `make check` in the plugin repository (ruff and the spec tests).
- The template's tests passing inside a generated project after `aegis add <name>`,
  under the queryspy strict gate.
- `make lint` and `make typecheck` in that generated project.

## Pitfalls

- Template files that are plain `.py` (not `.jinja`) are seen by the plugin
  repo's own ruff and pytest; the scaffold's `extend-exclude` and `testpaths`
  keep them out, because their import order is the project's and their tests
  import `app`.
- A path rendered by the template but missing from `FileManifest.primary` stays
  behind after `aegis remove <name>`, because removal walks only the manifest.
- `required_services` is the real version guard for a plugin that builds on a
  service: an older aegis-stack without that service refuses the add, while an
  `aegis_version` floor set ahead of a release blocks local development on the
  unreleased version.
- A timestamp a third-party API returns is often timezone-aware; the
  project's columns are naive UTC (`app.core.time.as_stored`), and Postgres
  refuses an aware value where SQLite accepts it, so test the mapping, not only
  the SQLite suite.
- A rendered test that hits the network makes the project's suite flaky and
  slow; every template test runs on recorded fixtures.
