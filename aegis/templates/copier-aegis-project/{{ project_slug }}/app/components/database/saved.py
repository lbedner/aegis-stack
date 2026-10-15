"""Saved queries: statements Overseer's Query keeps in the app's database,
by name, shared by every admin and opened again as a tab on any machine
(the tabs themselves stay in the browser). Kept again under its name, a
query is changed rather than doubled. Overseer's routes audit each save
and delete; this keeps rows only."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.db import get_async_session
from app.core.time import utcnow

from .models import NAME, SQL, SavedQuery


class SavedError(ValueError):
    """What was asked cannot be kept: no name or statement, or one too long."""


async def kept() -> list[SavedQuery]:
    """Every saved query, by name."""
    async with get_async_session() as db:
        return list(
            (await db.exec(select(SavedQuery).order_by(col(SavedQuery.name)))).all()
        )


async def keep(name: str, sql: str, *, by: str | None) -> SavedQuery:
    """``sql`` kept as ``name`` by ``by`` (who saved it; None with no one to
    sign in), the one already under that name changed; SavedError for an
    empty or too long name or statement, or one another admin kept under
    the same new name at the same moment."""
    name, sql = name.strip(), sql.strip()
    if not name or len(name) > NAME:
        raise SavedError(f"A saved query needs a name of 1 to {NAME} characters.")
    if not sql or len(sql) > SQL:
        raise SavedError(f"A saved query needs a statement of 1 to {SQL:,} characters.")
    async with get_async_session() as db:
        found = (
            await db.exec(select(SavedQuery).where(SavedQuery.name == name))
        ).first()
        query = found or SavedQuery(name=name, sql=sql)
        query.sql, query.saved_by, query.saved_at = sql, by, utcnow()
        db.add(query)
        try:
            await db.flush()  # its id, and a name taken at the same moment
        except IntegrityError:
            raise SavedError(
                f"{name!r} was saved by someone else just now: try again."
            ) from None
        db.expunge(query)  # kept as written: a commit would expire it
        await db.commit()
        return query


async def forget(query_id: int) -> str | None:
    """Delete the saved query ``query_id``: its name, or None where there
    was none."""
    async with get_async_session() as db:
        query = await db.get(SavedQuery, query_id)
        if query is None:
            return None
        await db.delete(query)
        await db.commit()
        return query.name
