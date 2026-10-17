"""Each part's facts the generated app reads, written from its PluginSpec
into the template as ``app/core/parts.py``. The spec stays the one place
they are kept: run ``make parts`` after changing one, and
``tests/core/test_parts_file.py`` fails while the file is stale. A
generated file in the template (not data passed at render time) is what
``aegis update`` carries to existing projects, like any template change."""

from pathlib import Path

from .components import COMPONENTS
from .plugins.spec import PartCategory, PluginSpec
from .services import SERVICES

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

'''


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
        "containers": spec.docker_services,
        "tier": spec.tier,
        "page": spec.page,
        "role": spec.role,
        "depends_on": spec.depends_on,
        "consumes": spec.consumes,
        "hosts": spec.hosts,
        "holds_keys": spec.holds_keys,
        "order": spec.order,
        "description": spec.description,
    }
    lines = [
        f"        {name}=Category.{value.name},"
        if name == "category"
        else f"        {name}={_value(value)},"
        for name, value in fields.items()
        if name in ("kind", "category", "cli") or not _default(value)
    ]
    return f'    "{spec.app_name}": Part(\n' + "\n".join(lines) + "\n    ),"


PART = """@dataclass(frozen=True)
class Part:
    kind: str  # component or service
    category: Category
    cli: str  # its name to the aegis CLI
    marker: str = ""  # a path only a stack with it has; empty: every stack
    containers: tuple[str, ...] = ()  # the compose services it adds
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
"""


def render() -> str:
    """``app/core/parts.py`` as the first-party specs declare it."""
    categories = "\n".join(f'    {c.name} = "{c.value}"' for c in PartCategory)
    specs = sorted((*COMPONENTS.values(), *SERVICES.values()), key=lambda s: s.app_name)
    entries = "\n".join(_entry(spec) for spec in specs)
    return (
        f"{HEADER}\nclass Category(StrEnum):\n{categories}\n\n\n{PART}\n\n"
        f"PARTS: dict[str, Part] = {{\n{entries}\n}}\n"
    )


if __name__ == "__main__":
    TEMPLATE_FILE.write_text(render())
    print(f"Wrote {TEMPLATE_FILE}")
