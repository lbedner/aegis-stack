"""Each part's facts the generated app reads, written from its PluginSpec
into the template as ``app/core/parts.py``. The spec stays the one place
they are kept: run ``make parts`` after changing one, and
``tests/core/test_parts_file.py`` fails while the file is stale. A
generated file in the template (not data passed at render time) is what
``aegis update`` carries to existing projects, like any template change."""

from pathlib import Path

from ..constants import (
    AnswerKeys,
    ComponentNames,
    PostgresProviders,
    StorageBackends,
    WorkerBackends,
)
from ..i18n.locales.en import MESSAGES
from .components import COMPONENTS
from .option_spec import OptionMode, OptionSpec
from .plugins.spec import PartCategory, PluginSpec
from .services import SERVICES
from .template_cleanup import run_ruff_on_text

REPO = Path(__file__).parents[2]

TEMPLATE_FILE = (
    Path(__file__).parents[1]
    / "templates"
    / "copier-aegis-project"
    / "{{ project_slug }}"
    / "app"
    / "core"
    / "parts.py"
)
HEADER = '''"""Each part this stack can have, as the aegis CLI declares it: its kind,
its concern (``Category``), its name on the CLI, what on disk says a stack
has it, the containers it adds and where Overseer's map draws it, by the
name the app knows it by. Generated from each part's PluginSpec by ``make parts`` in
aegis-stack: change the spec, not this file. A plugin's part declares its
own ``CATEGORY`` in its package."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

'''


# The axes the CLI still reads its older way (``extract_engine_info`` in
# template_generator), not through their specs' options: declared here, from
# the constants holding their choices, so the app sees every part whole.
# ponytail: one moves onto its spec's ``options`` once the CLI parses it
# generically (``database[neon]`` normalising to postgres is why not yet).
OLDER_AXES: dict[str, list[OptionSpec]] = {
    ComponentNames.DATABASE: [
        OptionSpec(
            name="engine",
            mode=OptionMode.SINGLE,
            choices=[StorageBackends.SQLITE, StorageBackends.POSTGRES],
            default=StorageBackends.DATABASE_DEFAULT,
            answer_key=AnswerKeys.DATABASE_ENGINE,
            about="guided.choice.db",
        ),
        OptionSpec(
            name="provider",
            mode=OptionMode.SINGLE,
            choices=PostgresProviders.ALL,
            default=PostgresProviders.DEFAULT,
            answer_key=AnswerKeys.POSTGRES_PROVIDER,
            about="guided.choice.db_provider",
        ),
    ],
    ComponentNames.SCHEDULER: [
        OptionSpec(
            name="backend",
            mode=OptionMode.SINGLE,
            choices=[
                StorageBackends.MEMORY,
                StorageBackends.SQLITE,
                StorageBackends.POSTGRES,
            ],
            default=StorageBackends.SCHEDULER_DEFAULT,
            answer_key=AnswerKeys.SCHEDULER_BACKEND,
            about="guided.choice.scheduler",
        ),
    ],
    ComponentNames.WORKER: [
        OptionSpec(
            name="backend",
            mode=OptionMode.SINGLE,
            choices=WorkerBackends.ALL,
            default=WorkerBackends.DEFAULT,
            answer_key=AnswerKeys.WORKER_BACKEND,
            about="guided.choice.worker",
        ),
    ],
}


def options_of(spec: PluginSpec) -> list[OptionSpec]:
    """What ``spec``'s part can be: its options, and its older axes."""
    return [*(spec.options or []), *OLDER_AXES.get(spec.name, [])]


def about(option: OptionSpec) -> dict[str, str]:
    """What each of ``option``'s choices means, in English, from the guided
    setup's strings (``about`` names their prefix): a provider's ``desc``
    with its ``pricing``."""
    found = {}
    for choice in option.choices if option.about else ():
        key = f"{option.about}.{choice.replace('-', '_')}"
        if key in MESSAGES:
            found[choice] = MESSAGES[key]
        elif f"{key}.desc" in MESSAGES:
            pricing = MESSAGES.get(f"{key}.pricing")
            desc = MESSAGES[f"{key}.desc"]
            found[choice] = f"{desc} ({pricing})" if pricing else desc
    return found


def _option(option: OptionSpec) -> str:
    """One ``Option``, by keyword, leaving out what is its default; the
    formatter lays it out (``render``)."""
    fields = {
        "name": option.name,
        "mode": option.mode.value,
        "choices": option.choices,
        "default": option.default,
        "answer": option.answer_key,
        "ordered": option.ordered,
    }
    given = [
        f"{name}={_value(value)}"
        for name, value in fields.items()
        if name in ("name", "mode", "choices") or not _default(value)
    ]
    if pairs := about(option):
        given.append(f"about=({''.join(f'({c!r}, {x!r}),' for c, x in pairs.items())})")
    return f"Option({', '.join(given)})"


def _value(value: object) -> str:
    """``value`` as Python source: a tuple for a list (one element keeps
    its comma)."""
    if isinstance(value, list):
        names = ", ".join(f'"{v}"' for v in value)
        return f"({names}{',' if len(value) == 1 else ''})"
    return f'"{value}"' if isinstance(value, str) else repr(value)


def _default(value: object) -> bool:
    """Whether ``value`` is a field's default: tier 0 is not ``False``."""
    return value is None or value is False or value == "" or value == []


def _entry(spec: PluginSpec) -> str:
    """One ``Part``, by keyword, leaving out what is its default."""
    fields = {
        "kind": spec.kind.value,
        "category": spec.category,
        "cli": spec.name,
        "marker": spec.marker_path,
        "containers": [
            *spec.docker_services,
            *(f"worker-{queue}" for queue in spec.worker_queue_names),
        ],
        "agents": spec.agents,
        "tier": spec.tier,
        "page": spec.page,
        "role": spec.role,
        "depends_on": spec.depends_on,
        "consumes": spec.consumes,
        "hosts": spec.hosts,
        "holds_keys": spec.holds_keys,
        "order": spec.order,
        "description": spec.description,
        "experimental": spec.experimental,
    }
    lines = [
        f"        {name}=Category.{value.name},"
        if name == "category"
        else f"        {name}={_value(value)},"
        for name, value in fields.items()
        if name in ("kind", "category", "cli") or not _default(value)
    ]
    if options := options_of(spec):
        lines.append(f"        options=({''.join(_option(o) + ',' for o in options)}),")
    return f'    "{spec.app_name}": Part(\n' + "\n".join(lines) + "\n    ),"


PART = """@dataclass(frozen=True)
class Option:
    \"\"\"One way a part can be built: the ontology's ``PartOption`` without
    this stack's choice, which ``answer`` keys in ``.copier-answers.yml``.\"\"\"

    name: str
    mode: Literal["single", "multi", "flag"]
    choices: tuple[str, ...]
    default: str | tuple[str, ...] | bool | None = None
    answer: str = ""
    ordered: bool = False
    about: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Part:
    kind: str  # component or service
    category: Category
    cli: str  # its name to the aegis CLI
    marker: str = ""  # a path only a stack with it has; empty: every stack
    containers: tuple[str, ...] = ()  # the compose services it adds
    # Dev-only services that act on the developer's machine for Overseer
    # (deploy-agent): shown on its page and in its logs, never on the map.
    agents: tuple[str, ...] = ()
    # Overseer's map: its row as a process of its own (0 the edge, 1 the
    # app, 2 its data; None: inside the webserver), data's shape (store,
    # bucket), the parts it calls and the ones it takes work from.
    tier: int | None = None
    page: str = ""  # its Overseer page, where that is not its name
    role: str = ""
    depends_on: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    hosts: bool = False  # what has no process of its own runs in it
    holds_keys: bool = False  # every outside provider's key lives in it
    order: int | None = None  # in the sidebar and its row; none: last, by name
    # What it is, in a line: what the app map says of a part with no
    # package docstring of its own (ingress is Traefik, not Python).
    description: str = ""
    # Its schema, APIs and CLI may change between releases.
    experimental: bool = False
    options: tuple[Option, ...] = ()  # what else it could be
"""


def render() -> str:
    """``app/core/parts.py`` as the first-party specs declare it."""
    categories = "\n".join(f'    {c.name} = "{c.value}"' for c in PartCategory)
    specs = sorted((*COMPONENTS.values(), *SERVICES.values()), key=lambda s: s.app_name)
    entries = "\n".join(_entry(spec) for spec in specs)
    source = (
        f"{HEADER}\nclass Category(StrEnum):\n{categories}\n\n\n{PART}\n\n"
        f"PARTS: dict[str, Part] = {{\n{entries}\n}}\n"
    )
    formatted = run_ruff_on_text(source, REPO, None)
    if formatted is None:
        raise RuntimeError("ruff could not format app/core/parts.py")
    return formatted


if __name__ == "__main__":
    TEMPLATE_FILE.write_text(render())
    print(f"Wrote {TEMPLATE_FILE}")
