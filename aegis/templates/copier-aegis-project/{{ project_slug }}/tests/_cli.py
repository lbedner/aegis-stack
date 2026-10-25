"""Run a project CLI command the way ``main()`` does, output captured."""

import asyncio
import inspect
import sys
from types import SimpleNamespace

import click
from typer.testing import CliRunner

from app.cli.main import app, run_command

runner = CliRunner()


def invoke(args: list[str], input: str | None = None) -> SimpleNamespace:
    """The runner's own ``invoke`` never awaits an async command, and
    awaiting it after the runner returns would print past the capture; so
    the command is parsed and its coroutine run by the harness, all inside
    one isolation. ``input`` is what the command reads from stdin."""
    code = 0
    with runner.isolation(input=input) as (stdout, _stderr, _output):
        try:
            value = app(args, standalone_mode=False)
            if inspect.iscoroutine(value):
                asyncio.run(run_command(value))
        except click.exceptions.Exit as exc:
            code = exc.exit_code
        except click.exceptions.ClickException as exc:
            exc.show()
            code = exc.exit_code
        except SystemExit as exc:
            # main() lets a command's sys.exit end the process with its code.
            code = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
        # print() is buffered in the runner's wrapper; the runner's own
        # invoke flushes it before reading, so this does too.
        sys.stdout.flush()
        output = stdout.getvalue().decode()
    return SimpleNamespace(exit_code=code, output=output)
