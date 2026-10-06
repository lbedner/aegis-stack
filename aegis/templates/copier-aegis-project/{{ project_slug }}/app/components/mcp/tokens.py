"""MCP tokens: the credential a person makes for an outside assistant that
reaches the app beyond stdio. One home for making, finding and revoking
them; the API, the CLI and Overseer all come through here.

A token belongs to a person and carries a scope, and the scope is the
grant: ``read`` reaches the granted read tools, ``propose`` the proposals
too (``scoped``). No second permission system, and never a write. Only a
hash is kept, so the value is shown once, when it is made. Writes are
flushed, not committed: the caller's session (a request's, the CLI's)
commits them.
"""

from collections.abc import Iterable
import hashlib
import secrets

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.core.tools import mcp_servable

from .models.tokens import McpToken

PREFIX = "mcp_"
# What each scope reaches, by the tools' effect.
SCOPES: dict[str, frozenset[str]] = {
    "read": frozenset({"read"}),
    "propose": frozenset({"read", "proposes"}),
}


def scoped(grant: Iterable[str], scope: str) -> list[str]:
    """The granted tools a token with ``scope`` may call."""
    return mcp_servable(grant, SCOPES[scope])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def create(
    db: AsyncSession, user_id: int, name: str, scope: str
) -> tuple[McpToken, str]:
    """A new token for ``user_id``: its row, and its value (shown once)."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope {scope!r}: one of {', '.join(SCOPES)}")
    value = PREFIX + secrets.token_urlsafe(32)
    row = McpToken(
        user_id=user_id,
        name=name,
        scope=scope,
        token_hash=_digest(value),
        hint=value[: len(PREFIX) + 4],
    )
    db.add(row)
    await db.flush()
    return row, value


async def resolve(db: AsyncSession, value: str) -> McpToken | None:
    """The live token ``value`` is, noting its use; None if it is unknown
    or revoked."""
    query = select(McpToken).where(
        McpToken.token_hash == _digest(value), col(McpToken.revoked_at).is_(None)
    )
    row = (await db.exec(query)).first()
    if row is None:
        return None
    row.last_used_at = utcnow()
    db.add(row)
    await db.flush()
    return row


async def live(db: AsyncSession, user_id: int) -> list[McpToken]:
    """``user_id``'s unrevoked tokens, newest first."""
    query = (
        select(McpToken)
        .where(McpToken.user_id == user_id, col(McpToken.revoked_at).is_(None))
        .order_by(col(McpToken.id).desc())
    )
    return list((await db.exec(query)).all())


async def revoke(db: AsyncSession, token_id: int, user_id: int) -> bool:
    """Revoke ``user_id``'s token ``token_id``: it fails on its next use.
    False if they have no live token by that id."""
    row = await db.get(McpToken, token_id)
    if row is None or row.user_id != user_id or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    db.add(row)
    await db.flush()
    return True
