"""Statement fragments more than one service builds its WHERE out of."""

from __future__ import annotations

from typing import Any


def owner_clause(column: Any, owner_user_id: int | None) -> Any:
    """Match one owner's rows; a NULL owner is the standalone (no auth)
    install, so ``owner_user_id=None`` means ``IS NULL``, not "no filter"."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id
