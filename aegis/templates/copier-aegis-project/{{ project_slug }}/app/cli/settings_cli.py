"""``settings``: the settings marked ``Configurable`` from the terminal.

These are not secrets, so a value goes in as an argument and is shown
whole. The rules are ``app.core.secrets``'s and ``saved_settings``'s: a
value is checked against the setting's type, kept in the secrets
component's store, and applies when the app restarts; one set in ``.env``
wins and is changed there.
"""

from typing import Annotated

from rich.table import Table
import typer

from app.cli import theme
from app.core import saved_settings, secrets
from app.core.audit import cli_actor

app = typer.Typer(help="List and save the settings marked Configurable.")
console = theme.console()

NAME = Annotated[str, typer.Argument(help="A setting, e.g. MEMORY_THRESHOLD_PERCENT.")]


def _setting(name: str) -> str:
    if not secrets.is_setting(name):
        theme.fail(f"{name} is not a Configurable setting (credentials: `secrets`).")
    return name


@app.command("list")
async def list_settings() -> None:
    """Every setting: its value, where it comes from, and its default."""
    table = Table(box=None, pad_edge=False)
    for column in ("Name", "Owner", "Source", "Value", "Default"):
        table.add_column(column)
    for row in await secrets.status(setting=True):
        table.add_row(
            row.name, row.owner, row.state, row.in_effect or "", row.default or ""
        )
    console.print(table)


@app.command("set")
async def set_setting(name: NAME, value: str) -> None:
    """Save a value; it applies when the app restarts."""
    try:
        await secrets.put(_setting(name), value, actor=cli_actor())
    except (secrets.SecretsReadOnlyError, secrets.SecretRejectedError) as exc:
        theme.fail(str(exc))
    theme.good(f"✓ {saved_settings.saved(name)}")


@app.command("reset")
async def reset_setting(name: NAME) -> None:
    """Remove a saved value: the default applies on restart."""
    try:
        await secrets.delete(_setting(name), actor=cli_actor())
    except secrets.SecretsReadOnlyError as exc:
        theme.fail(str(exc))
    theme.good(f"✓ {saved_settings.removed(name)}")
