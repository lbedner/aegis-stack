"""The framework's component and service tables, rendered from the specs.

The README and the docs index pages each carry a table between markers
(``<!-- aegis:components -->`` ... ``<!-- /aegis:components -->``); a
part added, renamed or described anew shows in all of them at once.
``make readme`` writes them, and ``tests/core/test_catalog_docs.py``
fails when one has drifted.
"""

import re
from pathlib import Path

from aegis.constants import DOCS_BASE_URL
from aegis.core.components import COMPONENTS, ComponentType
from aegis.core.plugins.spec import PluginSpec
from aegis.core.services import SERVICES

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    ROOT / "README.md",
    ROOT / "docs" / "components" / "index.md",
    ROOT / "docs" / "services" / "index.md",
)
KINDS = ("components", "services")
HEADERS = {"components": "Component", "services": "Service"}
ALWAYS = "![Always](https://img.shields.io/badge/-always_on-2ea043)"
OPTIONAL = "![Optional](https://img.shields.io/badge/-optional-blue)"
EXPERIMENTAL = "![Experimental](https://img.shields.io/badge/-experimental-orange)"
# The CLI is always there and has no spec of its own.
CLI_ROW = (
    f"| **[CLI]({DOCS_BASE_URL}cli-reference/)** "
    f"| Typer, first-class system interface | {ALWAYS} |"
)


def start(kind: str) -> str:
    return f"<!-- aegis:{kind} -->"


def end(kind: str) -> str:
    return f"<!-- /aegis:{kind} -->"


def title(spec: PluginSpec) -> str:
    """How the tables name a part: its own title, else its name."""
    return spec.title or spec.name.capitalize()


def _core(spec: PluginSpec) -> bool:
    return spec.type is ComponentType.CORE


def _row(spec: PluginSpec) -> str:
    badge = ALWAYS if _core(spec) else OPTIONAL
    if spec.experimental:
        badge = f"{badge} {EXPERIMENTAL}"
    link = f"{DOCS_BASE_URL}{spec.docs_path}/"
    return f"| **[{title(spec)}]({link})** | {spec.description} | {badge} |"


def table(kind: str) -> str:
    """The ``kind`` table: always-on parts first, then the rest by title."""
    specs = (COMPONENTS if kind == "components" else SERVICES).values()
    rows = [_row(s) for s in sorted(specs, key=lambda s: (not _core(s), title(s)))]
    if kind == "components":
        rows.insert(1, CLI_ROW)  # beside the backend it serves
    head = f"| {HEADERS[kind]} | What you get | |\n|---|---|---|"
    return "\n".join([head, *rows])


def rendered(text: str) -> str:
    """``text`` with each table between its markers rendered afresh."""
    for kind in KINDS:
        block = re.compile(
            rf"{re.escape(start(kind))}.*?{re.escape(end(kind))}", re.DOTALL
        )
        filled = f"{start(kind)}\n{table(kind)}\n{end(kind)}"
        text = block.sub(lambda _, block_text=filled: block_text, text)
    return text


def main() -> None:
    for path in FILES:
        path.write_text(rendered(path.read_text()))


if __name__ == "__main__":
    main()
