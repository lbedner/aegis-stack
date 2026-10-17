"""Every plugin describes itself in the generated README.

The README drifted because each feature needed its own hand-written
conditional in ``README.md.jinja``: redis was guarded on ``include_cache``
when the answer key is ``include_redis``, so it never rendered, and
finance, payment, documents and worker had no branch at all. A finance
blueprint produced a README that did not contain the word finance.

So the lines move to the spec that owns them, and this test is the rule
that keeps them there: a plugin cannot join the registry without saying
what it is and where to reach it, the same way it cannot skip a health
check.
"""

from __future__ import annotations

import re

import pytest

from aegis.core.component_files import PROJECT_SLUG_PLACEHOLDER, get_template_path
from aegis.core.components import COMPONENTS
from aegis.core.plugins.spec import PluginSpec, ReadmeWiring
from aegis.core.services import SERVICES

ALL_SPECS: dict[str, PluginSpec] = {**COMPONENTS, **SERVICES}


class TestEveryPluginCarriesReadmeWiring:
    @pytest.mark.parametrize("name", sorted(ALL_SPECS))
    def test_it_has_a_readme_section(self, name: str) -> None:
        spec = ALL_SPECS[name]
        assert isinstance(spec.readme, ReadmeWiring), (
            f"{name} has no ReadmeWiring, so it would render nowhere in the "
            f"generated README"
        )

    @pytest.mark.parametrize("name", sorted(ALL_SPECS))
    def test_it_says_where_to_reach_it(self, name: str) -> None:
        """A port, a path, or a CLI group. A row in the table with an
        empty second column is worse than no row."""
        reach = ALL_SPECS[name].readme.reach
        assert reach and reach.strip(), f"{name} does not say where to reach it"

    @pytest.mark.parametrize("name", sorted(ALL_SPECS))
    def test_its_prose_is_readme_grade(self, name: str) -> None:
        """``long_description`` is printed verbatim into the README now,
        not just the CLI picker, so the picker's shorthand shows.
        """
        spec = ALL_SPECS[name]
        text = spec.long_description or spec.description
        assert text, f"{name} has no description to print"
        assert not text.startswith("EXPERIMENTAL"), (
            f"{name} opens with a CLI-picker disclaimer; move the caveat "
            f"into the body so the README does not lead with it"
        )


class TestWiringShape:
    def test_first_steps_are_only_for_services(self) -> None:
        """ "First ten minutes" is about what the app DOES. A component
        has no first step of its own; redis is not something a new user
        opens."""
        for name, spec in COMPONENTS.items():
            assert not spec.readme.first_steps, (
                f"component {name} supplies first_steps; those belong to a "
                f"service, which is what a reader is actually here to use"
            )

    def test_required_env_is_a_subset_of_env_groups(self) -> None:
        """A variable called out as required has to be in a group the
        Configuration section actually prints, or the reader is told to
        set something they cannot find."""
        for name, spec in ALL_SPECS.items():
            if not spec.readme.required_env:
                continue
            assert spec.readme.env_groups, (
                f"{name} names required env vars but no env group to print them under"
            )


CLI_DIR = get_template_path() / PROJECT_SLUG_PLACEHOLDER / "app" / "cli"
PROJECT_CLI = "uv run <project_slug> "
# ``@x.command(...)`` (any other decorators) ``def fn``: x, its args, fn.
# Each further decorator is one line (``[^\n]``): under DOTALL a ``.*``
# there could span lines and backtrack exponentially (CodeQL py/redos).
COMMAND_DEF = re.compile(
    r"@(\w+)\.command\((.*?)\)[ \t]*\n(?:@[^\n]*\n)*(?:async )?def (\w+)", re.DOTALL
)
SUB_TYPER = re.compile(r"(\w+)\.add_typer\((\w+), name=\"([^\"]+)\"\)")
EXPLICIT_NAME = re.compile(r"^\s*(?:name=)?\"([^\"]+)\"|\bname=\"([^\"]+)\"")


def _group_source(group: str) -> str:
    """The template source of the typer app ``app/cli/main.py`` mounts
    as ``group``: its module, or every file of its package."""
    main = (CLI_DIR / "main.py.jinja").read_text()
    module = re.search(rf"\"{group}\": \(\"app\.cli\.(\w+)\", \"app\"\)", main)
    assert module, f"no CLI group {group!r} in app/cli/main.py's GROUPS"
    name = module.group(1)
    files = [*CLI_DIR.glob(f"{name}.py*"), *(CLI_DIR / name).glob("*.py*")]
    return "\n".join(f.read_text() for f in files)


def _resolves(words: list[str]) -> bool:
    """Whether ``group cmd [sub ...]`` names a command the generated CLI
    has, walking sub-typers; arguments (``<x>``) and options end the path."""
    source = _group_source(words[0])
    subs = {(m[0], m[2]): m[1] for m in SUB_TYPER.findall(source)}
    commands = set()
    for typer_var, args, func in COMMAND_DEF.findall(source):
        named = EXPLICIT_NAME.search(args)
        name = (named.group(1) or named.group(2)) if named else func
        commands.add((typer_var, name.replace("_", "-")))
    typer_var = "app"
    for word in words[1:]:
        if (typer_var, word) in commands:
            return True
        if (typer_var, word) not in subs:
            return False
        typer_var = subs[(typer_var, word)]
    return False


FIRST_STEP_COMMANDS = [
    (name, span)
    for name, spec in SERVICES.items()
    for step in spec.readme.first_steps
    for span in re.findall(r"`([^`]+)`", step)
]


class TestFirstStepsAreRealCommands:
    @pytest.mark.parametrize(("service", "command"), FIRST_STEP_COMMANDS)
    def test_it_runs_in_a_generated_project(self, service: str, command: str) -> None:
        """A first step is the first thing a reader types. ``make cli``
        never existed and neither did ``auth create-user``."""
        assert command.startswith(PROJECT_CLI), (
            f"{service} first step `{command}` is not a project CLI command "
            f"({PROJECT_CLI}<group> <command>)"
        )
        words = command.removeprefix(PROJECT_CLI).split()
        assert _resolves(words), f"{service} first step `{command}` does not exist"
