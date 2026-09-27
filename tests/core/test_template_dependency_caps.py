"""Every dependency a generated project installs has an upper bound.

A generated project resolves fresh on its first ``uv sync``: its lockfile is
written then, not shipped. So an open-ended requirement installs whatever
was released that morning, and a breaking release lands in every new
project before anyone has run it. taskiq 0.13 did exactly that (it dropped
an import taskiq-redis 1.0 relies on), and it was not the first. Capping
below the next breaking line keeps today's resolution and refuses the next
break; lifting a cap is a deliberate, tested bump.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement

from aegis.constants import AIFrameworks, AIProviders
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES
from aegis.core.template_generator import TemplateGenerator

PYPROJECT = (
    Path(__file__).parents[2]
    / "aegis/templates/copier-aegis-project/{{ project_slug }}/pyproject.toml.jinja"
)
# A requirement alone on its line, as dependency arrays write them.
_LINE = re.compile(r'^\s*"([A-Za-z0-9][^"]*)",?\s*(#.*)?$')
_UPPER = {"<", "<=", "==", "===", "~="}
# Template tags inside a requirement (conditional extras) render away.
_JINJA = re.compile(r"\{%.*?%\}|\{\{.*?\}\}")


def _template_requirements() -> list[str]:
    """Requirements in ``[project] dependencies`` and ``[dependency-groups]``.

    Only inside those arrays: the file's other quoted lists (ruff's rule
    codes) would parse as package names.
    """
    found, table, in_array = [], "", False
    for line in PYPROJECT.read_text().splitlines():
        if line.startswith("["):
            table = line.strip("[] ")
        elif re.match(r"^[a-z-]+ = \[\s*$", line):
            in_array = table == "dependency-groups" or (
                table == "project" and line.startswith("dependencies")
            )
        elif line.startswith("]"):
            in_array = False
        elif in_array and (match := _LINE.match(_JINJA.sub("", line))):
            found.append(match.group(1))
    return found


def _spec_requirements() -> list[str]:
    """The specs' own lists; ``{AI_FRAMEWORK_DEPS}`` is filled in by the
    generator and checked there."""
    specs = [*COMPONENTS.values(), *SERVICES.values()]
    return [
        dep
        for spec in specs
        for dep in (spec.pyproject_deps or [])
        if not dep.startswith("{")
    ]


def _generator_requirements() -> list[str]:
    """The dependency list ``aegis init`` previews, for every worker backend,
    database engine and AI framework."""
    found: list[str] = []
    services = [name for name in SERVICES if name != "ai"] + ["ai"]
    for framework in AIFrameworks.ALL:
        for worker in ("arq", "taskiq", "dramatiq"):
            for engine in ("sqlite", "postgres"):
                with (
                    patch(
                        "aegis.cli.interactive.get_ai_provider_selection",
                        return_value=sorted(AIProviders.ALL),
                    ),
                    patch(
                        "aegis.cli.interactive.get_ai_framework_selection",
                        return_value=framework,
                    ),
                ):
                    generator = TemplateGenerator(
                        project_name="caps",
                        selected_components=[
                            f"worker[{worker}]",
                            f"database[{engine}]",
                        ],
                        selected_services=services,
                    )
                    found += generator._get_pyproject_deps()
    return found


def _unbounded(requirements: list[str]) -> list[str]:
    return sorted(
        {
            req
            for req in requirements
            if not {s.operator for s in Requirement(req).specifier} & _UPPER
        }
    )


def test_the_template_finds_its_requirements() -> None:
    """The scan reads the real file (a guard that finds nothing guards nothing)."""
    assert len(_template_requirements()) > 40


@pytest.mark.parametrize(
    "source", [_template_requirements, _spec_requirements, _generator_requirements]
)
def test_every_requirement_has_an_upper_bound(source) -> None:  # noqa: ANN001
    assert _unbounded(source()) == []
