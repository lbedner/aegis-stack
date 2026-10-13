"""A user's signed-in sessions as the active-sessions views see them:
one live row per family (one per device), revoked one at a time, all
but the current one, or all of them."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.refresh_token import RefreshToken


class DevicesMixin:
    """``RefreshService``'s per-user half. It assigns ``db``; the family
    revoke these call back into lives on it."""

    db: AsyncSession

    if TYPE_CHECKING:

        async def revoke_family(self, family_id: str) -> None: ...

    async def revoke_all_for_user(self, user_id: int) -> None:
        """Mark every live refresh token for ``user_id`` revoked.

        Single UPDATE, no internal commit. The caller composes this into
        a larger transaction (password reset, account close) so the
        revoke and the cause-of-revoke land all-or-nothing.

        For interactive "sign out everywhere else" flows that own their
        own transaction, keep using :meth:`revoke_other_sessions`.
        """
        now = utcnow()
        stmt = (
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
            )
            .values(revoked_at=now)
        )
        await self.db.exec(stmt)  # type: ignore[call-overload]

    async def list_active_for_user(self, user_id: int) -> list[RefreshToken]:
        """Return all currently-live refresh rows for a user.

        Returns every row (not collapsed by family). Use
        :meth:`list_sessions` for the session-shaped view consumed by
        the active-sessions UI.
        """
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
            RefreshToken.expires_at > utcnow(),
        )
        result = await self.db.exec(stmt)
        return list(result.all())

    async def list_sessions(self, user_id: int) -> list[RefreshToken]:
        """Return one live row per ``family_id`` — i.e. one row per
        active device session.

        Picks the most recently created live row in each family so the
        UA/IP/last_used_at reflect the latest rotation. Ordered by
        ``last_used_at`` desc (nulls fall back to ``created_at``).
        """
        rows = await self.list_active_for_user(user_id)
        by_family: dict[str, RefreshToken] = {}
        for row in rows:
            current = by_family.get(row.family_id)
            if current is None or row.created_at > current.created_at:
                by_family[row.family_id] = row

        def _sort_key(r: RefreshToken) -> datetime:
            return r.last_used_at or r.created_at

        return sorted(by_family.values(), key=_sort_key, reverse=True)

    async def revoke_session(self, family_id: str, user_id: int) -> bool:
        """Revoke an entire session by ``family_id``, but only if it
        belongs to ``user_id``.

        Returns ``True`` if a live row was found and revoked, ``False``
        if no such row (wrong user, unknown family, or already revoked).
        """
        stmt = select(RefreshToken).where(
            RefreshToken.family_id == family_id,  # type: ignore[arg-type]
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
        )
        result = await self.db.exec(stmt)
        live_rows = list(result.all())
        if not live_rows:
            return False
        await self.revoke_family(family_id)
        return True

    async def revoke_other_sessions(self, keep_family_id: str, user_id: int) -> int:
        """Revoke every live row for ``user_id`` except those in
        ``keep_family_id``. Returns the count of *families* revoked
        (one increment per affected session, not per row)."""
        rows = await self.list_active_for_user(user_id)
        families = {r.family_id for r in rows if r.family_id != keep_family_id}
        if families:
            stmt = (
                update(RefreshToken)
                .where(
                    RefreshToken.family_id.in_(families),  # type: ignore[attr-defined]
                    RefreshToken.revoked_at.is_(None),  # type: ignore[union-attr]
                )
                .values(revoked_at=utcnow())
            )
            await self.db.exec(stmt)  # type: ignore[call-overload]
            await self.db.commit()
        return len(families)
