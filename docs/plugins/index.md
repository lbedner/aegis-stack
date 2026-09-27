# Plugins

A plugin adds a capability to an Aegis Stack project the same way the built-in
services do. It can bring API routes, settings, database tables, a CLI, a
health check and a dashboard card, and it is added and removed with the same
commands as auth, AI or payments.

A plugin is an ordinary Python package named `aegis-stack-<name>`. Installing
the package only puts it in your environment; `aegis add <name>` is what wires
it into a project.

## How a plugin gets into your project

```text
   PyPI, or a git URL
          |
          |  uv pip install aegis-stack-scraper
          v
   +---------------------+
   |  your environment   |    aegis plugins list    what is installed, and
   |  (the package is    |    aegis plugins info    can it be added here?
   |   now visible to    |
   |   the aegis CLI)    |
   +---------------------+
          |
          |  aegis add scraper
          v
   +------------------------------------------------------+
   |  your project                                        |
   |    - files rendered from the plugin's templates      |
   |    - routes, settings, health check, dashboard card  |
   |    - its own database tables, migrated               |
   |    - recorded in .copier-answers.yml                 |
   +------------------------------------------------------+
          |
          |  after upgrading the package:  aegis plugins update scraper
          |  to take it out again:          aegis remove scraper
          v
```

Two separate steps, on purpose. Getting the package is your package manager's
job, and works the same whether it came from PyPI, a git URL or a local path.
Configuring the project is Aegis's job, and it only happens when you ask for
it with `aegis add`.

## Commands

| Command | What it does |
|---|---|
| `aegis plugins list` | Installed plugins, and whether each can be added to the current project (`-p` to point at another). |
| `aegis plugins info <name>` | One plugin in detail: its options, tables, files, CLI, and what adding it would change here. |
| `aegis add <name>` | Add an installed plugin to the project: render its files, run its migrations, wire it in. |
| `aegis plugins update <name>` | Re-render a plugin's files after upgrading its package (`--all` for every plugin). |
| `aegis remove <name>` | Take the plugin out: every file it added, and its tables, after exporting their rows (see below). |
| `aegis plugins create <name>` | Scaffold a new plugin package. See [Creating a Plugin](creating.md). |
| `aegis plugins search` | Not available yet. Browse [aegis-stack.io/plugins](https://aegis-stack.io/plugins) instead. |

`list` and `info` check each plugin against the project before you add it:

| Status | Meaning |
|---|---|
| ready | Everything it needs is in place; `aegis add` will work. |
| missing component / service | It needs something the project does not have yet, such as the database. `aegis add` adds those first, then the plugin. |
| missing plugin | It depends on another plugin whose package is not installed. `aegis add` stops and tells you what to `pip install`. |
| conflict | It cannot sit alongside something already in the project. |
| already installed | It is already part of this project. |

## Removing a plugin keeps its data

`aegis remove <name>` deletes the plugin's files and writes one more
migration. That migration exports each of the plugin's tables to
`STORAGE_ROOT/plugin-exports/<table>/` as JSON lines, then drops the tables.
Adding the plugin again recreates them and loads the newest export back in.

Both steps run inside the migrations, so they happen wherever the migrations
are applied: on your machine when you run the command, and on a deployed
database when it next migrates. In the compose stack `STORAGE_ROOT` is the
`storage-data` volume, so exports outlive a deploy.

On the way back in, only the columns the table still has are loaded (a
plugin upgrade may have changed them), and a row the table refuses, such as
one pointing at a user who no longer exists, is skipped and logged.

## Finding plugins

The directory at [aegis-stack.io/plugins](https://aegis-stack.io/plugins)
lists every Aegis Stack plugin published to PyPI. Each listing shows what
the plugin does, the `aegis-stack` versions it supports and how to install
it.
`aegis-stack-crawl4ai`, a web-scraping plugin, is the reference example.

## Next

- [Creating a Plugin](creating.md): scaffold one, and how it plugs in.
- [Publishing a Plugin](publishing.md): PyPI, the directory, and naming.
