"""Retained Errors context, framework independent: the list (``load_list``)
and one issue's occurrences (``load_detail``), each read on its own."""

from collections.abc import Awaitable, Callable, Mapping
import json
from typing import Any

from app.core.formatting import page_number
from app.services.system.errors.client import repository, unavailable_reason
from app.services.system.errors.read import search
from app.services.system.errors.store import ErrorStore, StoreUnavailableError

PAGE_SIZE = 25
UNREADABLE = "Redis is unavailable. Retained errors cannot be read right now."
STALE = {
    "state": "degraded",
    "reason": "Collector status is unavailable or stale; collection may be paused.",
}
DEFAULTS: dict[str, Any] = {
    "error_rows": [],
    "error_total": 0,
    "error_status": STALE,
    "error_note": None,
    "error_detail": None,
    "error_history": [],
    "error_history_total": 0,
    "error_missing": False,
}
Part = Callable[[ErrorStore, Mapping[str, str]], Awaitable[dict[str, Any]]]


def page_of(query: Mapping[str, str], key: str = "page") -> int:
    return page_number(query.get(key))


def offset_of(query: Mapping[str, str], key: str = "page") -> int:
    return (page_of(query, key) - 1) * PAGE_SIZE


async def load_list(store: ErrorStore, query: Mapping[str, str]) -> dict[str, Any]:
    rows, total = await search(store, query, offset=offset_of(query), limit=PAGE_SIZE)
    raw = await store.call("get", store.key("status"))
    return {
        "error_rows": rows,
        "error_total": total,
        "error_status": json.loads(raw) if raw else STALE,
    }


async def load_detail(store: ErrorStore, query: Mapping[str, str]) -> dict[str, Any]:
    issue = query.get("issue", "")
    if not issue:
        return {}
    history, total = await store.occurrences(
        issue, offset=offset_of(query, "history_page"), limit=PAGE_SIZE
    )
    identity = query.get("occurrence") or (history[0].id if history else None)
    detail = await store.detail(identity) if identity else None
    if detail is not None and detail.fingerprint != issue:
        detail = None
    return {
        "error_detail": detail,
        "error_history": history,
        "error_history_total": total,
        "error_missing": detail is None,
    }


async def load(query: Mapping[str, str], part: Part = load_list) -> dict[str, Any]:
    """``part``'s context, or why there is none."""
    if reason := unavailable_reason():
        return empty("disabled", reason)
    store = repository()
    try:
        return DEFAULTS | await part(store, query)
    except StoreUnavailableError:
        return empty("degraded", UNREADABLE)
    finally:
        await store.client.aclose()


def empty(state: str, reason: str) -> dict[str, Any]:
    return DEFAULTS | {
        "error_status": {"state": state, "reason": reason},
        "error_note": reason,
    }
