"""The signed-in person's MCP tokens: list them, make one (its value shown
in this one answer), revoke one. The rules are ``app.components.mcp.tokens``'s;
these routes only say whose tokens they are."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.components.mcp import tokens
from app.components.mcp.models.tokens import (
    McpTokenCreate,
    McpTokenCreated,
    McpTokenResponse,
)
from app.core.db import get_async_db
from app.models.user import User
from app.services.auth.deps import get_current_active_user

router = APIRouter(prefix="/mcp/tokens", tags=["mcp"])


@router.get("", response_model=list[McpTokenResponse])
async def list_tokens(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> list[McpTokenResponse]:
    """Your live tokens, newest first; never their values."""
    rows = await tokens.live(db, user.id)
    return [McpTokenResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("", response_model=McpTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: McpTokenCreate,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> McpTokenCreated:
    """Make a token. Its value is in this answer and nowhere else."""
    row, value = await tokens.create(db, user.id, body.name, body.scope)
    shown = McpTokenResponse.model_validate(row, from_attributes=True)
    return McpTokenCreated(**shown.model_dump(), token=value)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: int,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Revoke one of your tokens: it fails on its next use."""
    if not await tokens.revoke(db, token_id, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
