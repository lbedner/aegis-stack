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
  Postgres schema of its own when it declares one;
- **its own worker queues**: `worker_queues=["crawler"]` names a queue module
  the plugin ships at `app/components/worker/queues/crawler.py`, and a stack
  with the worker component runs a `worker-crawler` container for it, one
  process, bind-mounted in dev like the stack's own workers. Gate the module on
  `include_worker` and write one branch per `worker_backend` (arq, TaskIQ,
  Dramatiq); without the component the file renders empty and nothing reads
  it.

The reference plugin, `aegis-stack-crawl4ai`, exercises most of that surface
and is the best example to read.

### What goes into the image

Four levers, in order of size. Pick the smallest that carries what you need:

| need | mechanism | ends up as |
| --- | --- | --- |
| a Python library | `pyproject_deps=["pillow>=11"]` | `pyproject.toml`, installed by `uv sync` |
| an apt package, tens of MB | `docker_packages=["ffmpeg", "poppler-utils"]` | `docker/apt-packages.txt`, installed in its own layer |
| a non-apt download, ~100 MB | `docker_steps=["fetch-model"]` plus `docker/build.d/fetch-model.sh` in your templates | run in name order by the build hook |
| 500 MB–1 GB (a model, a JVM, a GPU runtime) | `docker_services=["inference"]` and your own `docker/inference/Dockerfile` | a service of its own, talked to over HTTP |

`docker_packages` and `docker_steps` reach the image through two fixed hook
blocks in `Dockerfile.jinja`, which copy `docker/apt-packages.txt` and run
`docker/build.d/*.sh`. **The Dockerfile never mentions your plugin**, which is
the point: that file is `warn-if-diverged`, so a project that has added its own
build steps keeps its copy, and anything written into it by a plugin would
never arrive. The hooks are data, and `aegis add`/`aegis remove` rewrite that
data when plugins come and go — the same package requested by two plugins is
installed once.

Step scripts are files rather than commands on purpose: a `run this URL | sh`
string cannot be read in review, and would be interpolated into a shell.

## What a project finds by convention

Some of what a plugin contributes needs no wiring in `plugin.py`: the
project looks for a module of a known name in every service package, on
disk, and picks up a plugin's the same way as its own.

| File in `app/services/<your service>/` | What it holds |
|---|---|
| `__init__.py` | `CATEGORY = Category.DATA` (from `app.core.parts`): where the service sits in Overseer's grouping; App when left out |
| `models.py` (or a `models/` package) | the plugin's tables |
| `change_types.py` | changes a model proposes and the user approves |
| `scheduled_jobs.py` | `JOBS`, the jobs that run on a schedule |
| `aggregates.py` | `AGGREGATES`, what the plugin's data says about itself (`Aggregate` from `app.core.aggregates`): counts and sums an agent reads with `aggregate`, never rows |
| `tools.py` | tools an agent or an MCP client can be granted (`register_tool`) |

A scheduled job is a `ServiceJob` from `app.core.schedule`: the job
function, a stable id, a display name and the trigger. In a project with a
worker it runs on the worker. Without a scheduler the list is simply never
read, so a plugin can ship its jobs whether or not the project has one.

```python
# app/services/scraper/scheduled_jobs.py
from app.core.schedule import ServiceJob
from app.services.scraper.jobs import recrawl_sites_job

JOBS: tuple[ServiceJob, ...] = (
    ServiceJob(
        recrawl_sites_job,
        "scraper_recrawl",
        "Scraper: Recrawl Sites",
        {"trigger": "cron", "hour": 3},
    ),
)
```

Ids and function names are shared with every other service: prefix them
with the plugin's name.

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
