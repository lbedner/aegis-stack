"""``mcp-tokens``: make, list and revoke a person's MCP tokens
(``app.components.mcp.tokens``)."""

from typing import Annotated

import typer

from app.cli import theme
from app.components.mcp import tokens
from app.core.db import get_async_session
from app.core.formatting import format_relative_time
from app.models.user import User
from app.services.auth.users import UserService

app = typer.Typer(help="A person's MCP tokens, for clients beyond stdio.")
console = theme.console()

Email = Annotated[str, typer.Option("--email", help="Whose tokens.")]


async def _person(email: str) -> User:
    async with get_async_session() as db:
        user = await UserService(db).get_user_by_email(email)
    if user is None:
        console.print(f"No user {email}.", style=theme.ERROR)
        raise typer.Exit(1)
    return user


@app.command()
async def create(
    email: Email,
    name: Annotated[str, typer.Option("--name", help="What the token is for.")],
    scope: Annotated[
        str, typer.Option("--scope", help="read, or propose (read and propose).")
    ] = "read",
) -> None:
    """Make a token. Its value is printed this once."""
    user = await _person(email)
    async with get_async_session() as db:
        try:
            row, value = await tokens.create(db, user.id, name, scope)
        except ValueError as exc:
            console.print(str(exc), style=theme.ERROR)
            raise typer.Exit(1) from None
    console.print(f"Token {row.id} ({row.scope}) for {email}. Shown once:")
    console.print(value, soft_wrap=True)


@app.command("list")
async def list_tokens(email: Email) -> None:
    """A person's live tokens, newest first; never their values."""
    user = await _person(email)
    async with get_async_session() as db:
        rows = await tokens.live(db, user.id)
    if not rows:
        console.print(f"{email} has no tokens.")
        return
    for row in rows:
        used = format_relative_time(row.last_used_at) if row.last_used_at else "never"
        console.print(f"{row.id}  {row.name}  {row.scope}  {row.hint}...  used {used}")


@app.command()
async def revoke(
    email: Email,
    token_id: Annotated[int, typer.Argument(help="The token's id (from list).")],
) -> None:
    """Revoke a token: it fails on its next use."""
    user = await _person(email)
    async with get_async_session() as db:
        revoked = await tokens.revoke(db, token_id, user.id)
    if not revoked:
        console.print(f"{email} has no live token {token_id}.", style=theme.ERROR)
        raise typer.Exit(1)
    console.print(f"Token {token_id} revoked.")
