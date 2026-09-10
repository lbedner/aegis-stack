# Plugins

Aegis Stack projects extend through plugins: Python packages that ship a
`PluginSpec` and, usually, a template tree that lands in the project when
you run `aegis add <name>`. In-tree services and components are plugins
too; a third-party plugin uses the same dataclass and the same install path.

## Create one

```bash
aegis plugins create scraper --author "Your Name" --description "Web scraping for Aegis Stack"
cd aegis-stack-scraper
pip install -e .
aegis plugins list
```

The scaffold produces the distribution `aegis-stack-scraper` with the import
package `aegis_stack_scraper`, a `plugin.py` whose `get_spec()` returns the
`PluginSpec`, a `templates/{{ project_slug }}/` tree for files the plugin drops
into a project, and a test that pins the spec and the entry point.

`plugin.py` is where the plugin declares what it owns and how it wires in:
routers, settings mixins, health checks, dashboard cards and modals,
dependencies on components and services, migrations for its own tables.
The reference plugin, `aegis-stack-crawl4ai`, exercises most of that surface
and is the best example to read.

## How discovery works

`pyproject.toml` registers the spec under the `aegis.plugins` entry point
group:

```toml
[project.entry-points."aegis.plugins"]
scraper = "aegis_stack_scraper.plugin:get_spec"
```

Any `aegis` command run in an environment where the package is installed
sees it. `aegis plugins list` shows what is installed, `aegis add scraper`
installs it into a project, `aegis plugins update` re-renders after an
upgrade, and `aegis remove scraper` walks the spec's file manifest to take
it out again.

A plugin that declares `migrations` gets them written and applied on
`aegis add`, with a Postgres schema of its own when it declares one.

Dependencies can name a variant. `required_services = ["auth[org]"]` asks
for auth at org level: `aegis add` installs it at that level when the
project has no auth, upgrades it when the project is at basic or rbac,
and does nothing when org is already there. A request that would swap an
unordered choice, such as `ai[langchain]` on a pydantic-ai project, is
refused with a message rather than applied silently.

## Publish and get listed

Publish to PyPI as you would any package. The plugin directory at
[aegis-stack.io/plugins](https://aegis-stack.io/plugins) sweeps PyPI nightly
and lists every package that is an Aegis Stack plugin. It finds candidates
from three markers the scaffold already set:

| marker | where |
|---|---|
| name starts with `aegis-stack-` | `[project] name` |
| `aegis-stack-plugin` keyword | `[project] keywords` |
| `Aegis Plugin` project URL | `[project.urls]` |

A candidate is confirmed by downloading its latest wheel and reading the
`aegis.plugins` entry point out of `entry_points.txt`. The directory never
imports or runs plugin code. Packages that carry a marker but no entry point
stay off the public list.

Listings are either verified or community. Verified means a maintainer
reviewed the plugin; first-party plugins carry it. Everything else lists as
community with the same detail page: summary, latest release, supported
`aegis-stack` versions, downloads, repository and PyPI links, and the install
command.

### Source-only plugins

A plugin does not have to be on PyPI to work. `aegis` never installs anything
itself: discovery is the `aegis.plugins` entry point on whatever is in the
environment, so a plugin installed from a path or a git URL is found exactly
like a published one.

```bash
uv pip install git+https://github.com/you/aegis-stack-scraper
aegis add scraper
```

The directory lists these in their own section, separate from published
plugins. It finds them by GitHub topic, which is the only marker GitHub
indexes; the PyPI keyword is invisible there.

```text
topic:aegis-stack-plugin
```

The two sections are not cosmetic. A published plugin resolves by version, so
its listing carries a version, the `aegis-stack` range it supports, and a
copyable install command. A source-only plugin installs from a mutable branch
and pins nothing, so its listing carries the repository link and says so, and
offers no install one-liner. Publishing to PyPI later moves the entry to the
published section; nothing about the plugin has to change.

For a same-day listing, or for a package published without the markers,
submit the PyPI name at
[aegis-stack.io/plugins/submit](https://aegis-stack.io/plugins/submit). The
same verification runs on the spot.

## Naming

The `aegis-stack-` prefix is deliberate. PyPI carries close to two hundred
unrelated `aegis*` projects; `aegis-stack-` is the one namespace this project
owns, so the directory can trust it as a signal. The install identifier is the
short name after the prefix: `aegis add scraper`, never
`aegis add aegis-stack-scraper`.
