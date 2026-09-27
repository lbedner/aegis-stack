# Publishing a Plugin

## Get listed

Publish to PyPI as you would any package. The plugin directory at
[aegis-stack.io/plugins](https://aegis-stack.io/plugins) sweeps PyPI nightly
and lists every package that is an Aegis Stack plugin. It finds candidates
by either of two markers, both of which the scaffold sets:

| marker | where |
|---|---|
| name starts with `aegis-stack-` | `[project] name` |
| `aegis-stack-plugin` keyword | `[project] keywords` |

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

The directory lists published packages only; a plugin that lives only in a
repository is not listed. Publishing it to PyPI gets it listed, and nothing
about the plugin has to change.

## Naming

The `aegis-stack-` prefix is deliberate. PyPI carries close to two hundred
unrelated `aegis*` projects; `aegis-stack-` is the one namespace this project
owns, so the directory can trust it as a signal. The install identifier is the
short name after the prefix: `aegis add scraper`, never
`aegis add aegis-stack-scraper`.
