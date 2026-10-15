"""Query's saved queries (Overseer > Database > Query, its Saved menu): a
tab kept by name in the app's database for every admin
(``app.components.database.saved``), opened again as a tab on any machine,
or deleted. The menu reads the list as it opens and again on ``REFRESH``,
which a save or a delete answers with beside its toast, so only the list
ever lists. The routes audit each save and delete; all of it is refused
where a table's rows are hidden, as Query is (``_shown``)."""

from typing import Any

from fastapi import HTTPException

from app.core import exposure

# Where the list is read, a tab saved and a saved query deleted (audited),
# what lists them, and the event a change tells the list to read again by.
QUERY_SAVE = "/partials/overseer/database/queries"
QUERY_FORGET = "/partials/overseer/database/queries/{query_id}/forget"
QUERY_SAVED = "pages/overseer/database/_query_saved.html"
REFRESH = "saved-queries"


def _shown() -> None:
    """Not found where a table's rows are hidden."""
    if exposure.refusal(exposure.ROWS):
        raise HTTPException(status_code=404)


async def saved_queries() -> dict[str, Any]:
    """The queries kept for every admin, as Query's Saved menu lists them,
    each with where it is deleted."""
    from app.components.database import saved  # with the database component

    _shown()
    return {
        "saved_queries": [
            {
                "name": q.name,
                "sql": q.sql,
                "hint": q.sql[:300]
                + (f" (saved by {q.saved_by})" if q.saved_by else ""),
                "forget": QUERY_FORGET.format(query_id=q.id),
            }
            for q in await saved.kept()
        ],
        "query_save": QUERY_SAVE,
        "saved_refresh": REFRESH,
    }


async def save_query(name: str, sql: str, by: str | None) -> tuple[str, str]:
    """``sql`` kept as ``name`` for every admin (a query kept under it
    changed): how it went, for the audit (saved, refused), and what the
    toast says."""
    from app.components.database import saved  # with the database component

    _shown()
    try:
        query = await saved.keep(name, sql, by=by)
    except saved.SavedError as exc:
        return "refused", str(exc)
    return "saved", f"Saved {query.name}."


async def forget_query(query_id: int) -> tuple[str, str, str]:
    """Delete the saved query ``query_id``: how it went and its name, for
    the audit, and what the toast says."""
    from app.components.database import saved  # with the database component

    _shown()
    name = await saved.forget(query_id)
    if name is None:
        return "missing", str(query_id), "It was deleted already."
    return "forgotten", name, f"Deleted {name}."
