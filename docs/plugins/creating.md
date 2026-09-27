# Creating a Plugin

## Scaffold one

```bash
aegis plugins create scraper --author "Your Name" --description "Web scraping for Aegis Stack"
cd aegis-stack-scraper
pip install -e .
aegis plugins list
```

The scaffold produces:

```text
aegis-stack-scraper/                        the distribution
  pyproject.toml                            registers the plugin (see below)
  src/aegis_stack_scraper/                  the import package
    plugin.py                               get_spec(): what the plugin is
    templates/{{ project_slug }}/           files that land in a project
  tests/test_plugin.py                      pins the spec and the registration
  Makefile, .pre-commit-config.yaml,
  .github/workflows/test.yml                lint and test, locally and in CI
```

## What `plugin.py` declares

`get_spec()` returns a `PluginSpec`, the same declaration the built-in
services and components use. It is a description, not code that runs in the
project: Aegis reads it to know what to render, wire and migrate when someone
runs `aegis add scraper`.

It declares:

- **what the plugin owns**: the files its templates produce, so `aegis remove`
  can take exactly those out again;
- **how it wires in**: routers, settings, health checks, dashboard cards and
  modals, CLI commands;
- **what it needs**: components and services it depends on;
- **its own tables**: migrations, written and applied on `aegis add`, in a
  Postgres schema of its own when it declares one.

The reference plugin, `aegis-stack-crawl4ai`, exercises most of that surface
and is the best example to read.

## Depending on a service variant

Dependencies can name a variant. `required_services = ["auth[org]"]` asks for
auth at org level: `aegis add` installs it at that level when the project has
no auth, upgrades it when the project is at basic or rbac, and does nothing
when org is already there. A request that would swap an unordered choice, such
as `ai[langchain]` on a pydantic-ai project, is refused with a message rather
than applied silently.

## How the CLI finds it

`pyproject.toml` registers the spec under the `aegis.plugins` entry point
group:

```toml
[project.entry-points."aegis.plugins"]
scraper = "aegis_stack_scraper.plugin:get_spec"
```

Any `aegis` command run in an environment where the package is installed sees
it, whether it was installed from PyPI, a git URL or a local path. `aegis`
never installs packages itself.

When the plugin works locally, see [Publishing a Plugin](publishing.md).
