"""``secrets``: the secrets component's store from the terminal.

A value comes in through a hidden prompt, or stdin when piped
(``op read ... | app secrets set NAME``), never as an argument, where it
would land in shell history and the process list. Nothing prints a value
back: ``list`` shows where each key is set and its last four characters.
The rules (declared names, ``.env`` wins, provider checks) are
``app.core.secrets``'s.
"""

import sys
from typing import Annotated

from rich.table import Table
import typer

from app.cli import theme
from app.core import secrets
from app.core.audit import cli_actor

app = typer.Typer(help="Set, list and test the credentials the app reads.")
console = theme.console()

NAME = Annotated[str, typer.Argument(help="A declared name, e.g. RESEND_API_KEY.")]
MARKS = {
    secrets.VERIFIED: theme.ACCENT,
    secrets.UNVERIFIED: theme.WARNING,
    secrets.REJECTED: theme.ERROR,
}


def _say(verdict: secrets.Verdict) -> None:
    console.print(f"[{MARKS[verdict.result]}]{verdict.result}[/] {verdict.message}")


def _read_value(name: str) -> str:
    if sys.stdin.isatty():
        return typer.prompt(name, hide_input=True).strip()
    return sys.stdin.read().strip()


def _state(row: secrets.SecretStatus) -> str:
    """Where it is set; unset, whether something enabled needs it."""
    if not row.is_set and row.needed:
        return f"[{theme.WARNING}]{row.state}[/]"
    return row.state


@app.command("list")
async def list_secrets() -> None:
    """Every declared key: where it is set, never the value."""
    table = Table(box=None, pad_edge=False)
    for column in ("Name", "Owner", "State", "Value"):
        table.add_column(column)
    for row in await secrets.status():
        hint = row.hint and (f"•••• {row.hint}" if row.secret else row.hint)
        table.add_row(row.name, row.owner, _state(row), hint or "")
    console.print(table)


@app.command("set")
async def set_secret(name: NAME) -> None:
    """Store a key (hidden prompt, or stdin); the provider checks it first."""
    value = _read_value(name)
    if not value:
        theme.fail(f"No value given for {name}.")
    try:
        verdict = await secrets.put(name, value, actor=cli_actor())
    except (
        secrets.UnknownSecretError,
        secrets.SecretsReadOnlyError,
        secrets.SecretRejectedError,
    ) as exc:
        theme.fail(str(exc))
    console.print(f"[{theme.ACCENT}]✓[/] {name} saved")
    if verdict is not None:
        _say(verdict)


@app.command("delete")
async def delete_secret(name: NAME) -> None:
    """Remove a stored key."""
    try:
        await secrets.delete(name, actor=cli_actor())
    except (secrets.UnknownSecretError, secrets.SecretsReadOnlyError) as exc:
        theme.fail(str(exc))
    console.print(f"[{theme.ACCENT}]✓[/] {name} removed")


@app.command("test")
async def check_secret(name: NAME) -> None:
    """Ask the provider whether the key in effect works."""
    try:
        verdict = await secrets.test(name)
    except secrets.UnknownSecretError as exc:
        theme.fail(str(exc))
    _say(verdict)
    if verdict.result == secrets.REJECTED:
        raise typer.Exit(1)
