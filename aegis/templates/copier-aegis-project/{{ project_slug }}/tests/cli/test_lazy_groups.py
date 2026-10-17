"""The CLI's command groups load when run (``app.cli.main.LazyGroups``):
a command imports its own group, not every group's; a listing shows them
all, in the table's order."""

import subprocess
import sys

import click
import typer

from app.cli.main import GROUPS, app
from tests._cli import invoke

# Runs ``health --help`` in a fresh interpreter and prints the other
# groups' modules it imported.
PROBE = """
import sys
from app.cli.main import GROUPS, app
try:
    app(["health", "--help"], standalone_mode=False)
except SystemExit:
    pass
print([m for g, (m, _) in GROUPS.items() if g != "health" and m in sys.modules])
"""


def test_a_command_imports_only_its_own_group() -> None:
    """``health`` never pulls in another group (the AI chat's imports were
    most of every server read's start-up)."""
    done = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip().splitlines()[-1] == "[]"


def test_the_listing_shows_the_groups_this_stack_has_in_order() -> None:
    group = typer.main.get_command(app)
    assert isinstance(group, click.Group)
    with click.Context(group) as ctx:
        listed = group.list_commands(ctx)
    assert "health" in listed
    assert listed == [name for name in GROUPS if name in listed]


def test_an_unknown_group_is_refused() -> None:
    assert invoke(["no-such-group"]).exit_code != 0
