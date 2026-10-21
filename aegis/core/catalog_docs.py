"""The framework's component and service tables, rendered from the specs.

The README and the docs index pages each carry a table between markers
(``<!-- aegis:components -->`` ... ``<!-- /aegis:components -->``); a
part added, renamed or described anew shows in all of them at once.
``make readme`` writes them, and ``tests/core/test_catalog_docs.py``
fails when one has drifted.
"""

import re
from pathlib import Path

import yaml

from aegis.constants import DOCS_BASE_URL, AnswerKeys
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


# A generated project's README section listing what it has. No ``aegis:``
# in it: that prefix marks a template's policy annotation, which never
# reaches a rendered file.
PARTS_START = "<!-- what-it-has -->"
PARTS_END = "<!-- /what-it-has -->"


def start(kind: str) -> str:
    return f"<!-- aegis:{kind} -->"


def end(kind: str) -> str:
    return f"<!-- /aegis:{kind} -->"


def _core(spec: PluginSpec) -> bool:
    return spec.type is ComponentType.CORE


def _row(spec: PluginSpec) -> str:
    badge = ALWAYS if _core(spec) else OPTIONAL
    if spec.experimental:
        badge = f"{badge} {EXPERIMENTAL}"
    link = f"{DOCS_BASE_URL}{spec.docs_path}/"
    return f"| **[{spec.display_title}]({link})** | {spec.description} | {badge} |"


def table(kind: str) -> str:
    """The ``kind`` table: always-on parts first, then the rest by title."""
    specs = (COMPONENTS if kind == "components" else SERVICES).values()
    rows = [
        _row(s) for s in sorted(specs, key=lambda s: (not _core(s), s.display_title))
    ]
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


def installed(project: Path) -> list[PluginSpec]:
    """The components and services ``project`` has, by its answers: every
    always-on component, and each part whose ``include_<name>`` is on."""
    answers_file = project / AnswerKeys.ANSWERS_FILENAME
    answers = yaml.safe_load(answers_file.read_text()) if answers_file.exists() else {}
    on = {key for key, value in (answers or {}).items() if value is True}
    return [
        spec
        for spec in [*COMPONENTS.values(), *SERVICES.values()]
        if _core(spec) or f"include_{spec.name}" in on
    ]


def _part_line(spec: PluginSpec) -> str:
    reach = f" ({spec.readme.reach})" if spec.readme.reach else ""
    return f"- **{spec.display_title}**: {spec.description}{reach}"


def parts_list(specs: list[PluginSpec]) -> str:
    """A project's README section: its components, then its services."""
    lines: list[str] = []
    for heading, kind in (("Components", COMPONENTS), ("Services", SERVICES)):
        mine = [s for s in specs if s.name in kind and kind[s.name] is s]
        if mine:
            lines += [f"### {heading}", "", *map(_part_line, mine), ""]
    lines.append(
        "Each part's routes, jobs and tables: the docs' *What It Is Made Of* "
        "page (`stack.md`), read from the code when the docs are built."
    )
    return "\n".join(lines)


def fill_readme(project: Path) -> None:
    """``project``'s README with what it has between its parts markers;
    a README without them (rewritten by its owner) is left alone."""
    readme = project / "README.md"
    if not readme.exists() or PARTS_START not in readme.read_text():
        return
    block = re.compile(rf"{re.escape(PARTS_START)}.*?{re.escape(PARTS_END)}", re.DOTALL)
    filled = f"{PARTS_START}\n{parts_list(installed(project))}\n{PARTS_END}"
    readme.write_text(block.sub(lambda _: filled, readme.read_text()))


def main() -> None:
    for path in FILES:
        path.write_text(rendered(path.read_text()))


if __name__ == "__main__":
    main()
