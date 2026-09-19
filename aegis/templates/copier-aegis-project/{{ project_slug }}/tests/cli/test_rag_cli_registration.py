"""Every ``rag`` command is registered on the group `main.py` mounts.

``app/cli/rag`` is a package: the Typer app lives in ``shared`` and the
commands are decorated across four sibling modules, so registration
depends on ``__init__`` importing each of them. Those imports look
unused, and an import sorter, a linter's autofix, or a well-meaning
cleanup can remove them.

Nothing else notices if they go. The package still imports, ruff and
ty stay green, and ``aegis init`` renders a project whose whole suite
passes - the only symptom is ``rag --help`` listing nothing, which no
existing test asks about. That is exactly what happened while this
package was being split: the ``@app.command`` decorators were dropped,
every check stayed green, and the CLI was silently empty.

So this asserts the count and the names, not just that the module
imports.
"""

from __future__ import annotations

import importlib


# What `rag --help` must offer. Names, not function names: these are the
# strings a user types, so renaming one is a user-visible change that
# should fail here and be decided deliberately.
EXPECTED_COMMANDS = {
    "add",
    "delete",
    "files",
    "index",
    "install-model",
    "list",
    "remove",
    "search",
    "status",
}


def _registered() -> set[str]:
    package = importlib.import_module("app.cli.rag")
    return {command.name for command in package.app.registered_commands}


def test_every_command_is_registered() -> None:
    missing = sorted(EXPECTED_COMMANDS - _registered())
    assert not missing, (
        f"{missing} are not registered on the rag group. The most likely "
        f"cause is a dropped import in app/cli/rag/__init__.py - those "
        f"imports are what run the @app.command decorators."
    )


def test_no_command_appeared_unannounced() -> None:
    """A new command is fine; it just has to be named here, so the set
    stays the record of what the group offers."""
    extra = sorted(_registered() - EXPECTED_COMMANDS)
    assert not extra, f"new rag commands not recorded in this test: {extra}"


def test_the_group_is_the_one_shared_defines() -> None:
    """``main.py`` reads ``rag.app``. If the package ever exposed a
    different Typer instance than the one the commands decorate, the
    group would mount empty with every command still 'registered'
    somewhere else."""
    package = importlib.import_module("app.cli.rag")
    shared = importlib.import_module("app.cli.rag.shared")
    assert package.app is shared.app
