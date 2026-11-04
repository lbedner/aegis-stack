"""
Menu command implementation.
"""

import json
from typing import Any

import typer

from ..core.menu import menu
from ..core.selection import SelectionError, init_command_for


def _print(data: dict[str, Any]) -> None:
    typer.echo(json.dumps(data, indent=2))


def menu_command(
    name: str = typer.Option(
        "my-app", "--name", "-n", help="Project name for the init command."
    ),
    components: str | None = typer.Option(
        None, "--components", "-c", help="A selection to check, as init takes it."
    ),
    services: str | None = typer.Option(
        None, "--services", "-s", help="A selection to check, as init takes it."
    ),
) -> None:
    """Print the generator's menu as JSON, or check a selection against it.

    With no selection: every component and service, its options, and what
    it requires, recommends and conflicts with. With --components and/or
    --services: the init command that builds it ({"command": ...}), or the
    rules init refuses it for ({"rules": [...], "missing": [...]}, exit 1).
    """
    if components is None and services is None:
        _print(menu())
        return
    try:
        _print({"command": init_command_for(name, components, services)})
    except SelectionError as e:
        _print({"rules": e.rules, "missing": e.missing})
        raise typer.Exit(1) from None
