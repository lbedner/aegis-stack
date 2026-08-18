"""The one piece of state every facade mixin shares.

A mixin cannot stand alone - it exists to be composed into
``FinanceService`` - but each one still needs to say what it assumes, or a
type checker reads ``self.db`` as an error in eleven files.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession


class FinanceServiceBase:
    """Holds the session the mixins delegate with."""

    db: AsyncSession

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
