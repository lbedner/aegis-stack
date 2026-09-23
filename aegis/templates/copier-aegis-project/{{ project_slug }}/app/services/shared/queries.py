"""Statement fragments more than one service builds its WHERE out of."""

from __future__ import annotations

from typing import Any


def owner_clause(column: Any, owner_user_id: int | None) -> Any:
    """Match one owner's rows; a NULL owner is the standalone (no auth)
    install, so ``owner_user_id=None`` means ``IS NULL``, not "no filter"."""
    return column.is_(None) if owner_user_id is None else column == owner_user_id


def owner_filters(column: Any, owner_user_id: int | None) -> list[Any]:
    """Clauses scoping ``column`` to one owner, for ``.where(*...)``.

    Unlike ``owner_clause``, ``None`` means "no filter": a standalone
    install reads every row.
    """
    return [] if owner_user_id is None else [column == owner_user_id]


def stored_owner(owner_user_id: int | None) -> int:
    """The owner a NOT NULL owner column stores: ``0`` for a standalone
    (no auth) install, else the user."""
    return 0 if owner_user_id is None else owner_user_id
