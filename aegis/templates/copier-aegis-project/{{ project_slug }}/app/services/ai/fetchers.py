"""Memory-module fetcher registry.

The dynamic half of memory modules: a ``memory_module`` row's
``fetch_function`` names a fetcher registered here, and the context
renderer runs it per request to pull live, per-user data into the
prompt. Mirrors the tool registry (``tools.py``): the database decides
WHICH fetchers a module uses; this module decides WHAT each name runs.

Applications register their own domain fetchers at import time:

    from app.services.ai.fetchers import FetchContext, register_fetcher

    async def fetch_open_orders(ctx: FetchContext) -> str | None:
        \"\"\"Summarize the user's open orders.\"\"\"
        ...

    register_fetcher("fetch_open_orders", fetch_open_orders)

A module row naming an unregistered fetcher, or a fetcher that raises,
degrades that one module with a warning - never the chat turn.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.log import logger


@dataclass(frozen=True)
class FetchContext:
    """What a fetcher gets to work with.

    ``session`` optionally carries an AsyncSession so callers can inject
    a transaction (tests do); fetchers open their own session when None.
    """

    user_id: str
    days_back: int | None = None
    session: Any | None = None


FetcherFunc = Callable[[FetchContext], Awaitable[str | None]]


@dataclass(frozen=True)
class RegisteredFetcher:
    """A named fetcher entry: the coroutine function plus metadata."""

    name: str
    func: FetcherFunc
    description: str | None = None


_registry: dict[str, RegisteredFetcher] = {}


def register_fetcher(
    name: str,
    func: FetcherFunc,
    *,
    description: str | None = None,
    replace: bool = False,
) -> None:
    """Register a fetcher under a name.

    Raises ValueError on a duplicate name unless ``replace=True``, so two
    modules can't silently fight over one name.
    """
    if not replace and name in _registry:
        raise ValueError(
            f"Fetcher '{name}' is already registered; pass replace=True to rebind it"
        )
    _registry[name] = RegisteredFetcher(name=name, func=func, description=description)


def unregister_fetcher(name: str) -> None:
    """Remove a registered fetcher. Raises KeyError if the name is unknown."""
    try:
        del _registry[name]
    except KeyError:
        raise KeyError(f"Fetcher '{name}' is not registered") from None


def get_fetcher(name: str) -> RegisteredFetcher | None:
    """Return the registry entry for a name, or None if unregistered."""
    return _registry.get(name)


def registered_fetcher_names() -> list[str]:
    """All currently registered fetcher names, in registration order."""
    return list(_registry)


async def run_fetcher(name: str, ctx: FetchContext) -> str | None:
    """Run a fetcher by name, degrading failures to None with a warning.

    Both failure modes - an unknown name (stale module row) and a fetcher
    that raises (flaky data source) - skip this module's dynamic half
    rather than breaking the turn. Never silent: both are logged.
    """
    entry = _registry.get(name)
    if entry is None:
        logger.warning(
            "Fetcher has no registered callable; skipping", fetch_function=name
        )
        return None
    try:
        return await entry.func(ctx)
    except Exception as exc:
        logger.warning(
            "Fetcher failed; skipping its module content",
            fetch_function=name,
            error=str(exc),
        )
        return None
