"""The provider commands run at all: ``ai providers``, ``ai add-provider``
and ``ai use-provider`` import their helpers inside the command body, so a
wrong import path only fails when someone types the command. All three
once reached for ``app.cli.services`` (a relative import one level short)
and died before doing anything."""

import ast
from pathlib import Path

from typer.testing import CliRunner

from app.cli.ai import providers as providers_cli

MODULE = Path(providers_cli.__file__)


def test_ai_providers_prints_the_table() -> None:
    result = CliRunner().invoke(providers_cli.app, ["providers"])
    assert result.exit_code == 0, result.output
    assert "Anthropic" in result.output


def test_every_command_import_resolves() -> None:
    """Each function-local ``from ... import`` in the module names a real
    module, checked without running commands that write to ``.env``."""
    import importlib

    tree = ast.parse(MODULE.read_text())
    package = providers_cli.__package__
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            name = ("." * node.level) + node.module
            importlib.import_module(name, package=package if node.level else None)
