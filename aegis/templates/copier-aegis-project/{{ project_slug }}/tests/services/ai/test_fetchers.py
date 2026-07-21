"""Tests for the memory-module fetcher registry."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from app.services.ai.fetchers import (
    FetchContext,
    register_fetcher,
    registered_fetcher_names,
    run_fetcher,
    unregister_fetcher,
)


@pytest.fixture(autouse=True)
def clean_registry() -> Generator[None]:
    """Remove fetchers registered by a test so cases stay independent."""
    before = set(registered_fetcher_names())
    yield
    for name in set(registered_fetcher_names()) - before:
        unregister_fetcher(name)


async def _orders(ctx: FetchContext) -> str | None:
    """Return recent orders for the user."""
    return f"orders for {ctx.user_id} (last {ctx.days_back} days)"


class TestRegistration:
    def test_register_and_list(self) -> None:
        register_fetcher("fetch_orders", _orders)

        assert "fetch_orders" in registered_fetcher_names()

    def test_duplicate_registration_is_an_error(self) -> None:
        register_fetcher("fetch_orders", _orders)

        with pytest.raises(ValueError, match="already registered"):
            register_fetcher("fetch_orders", _orders)

    def test_unregister_unknown_is_an_error(self) -> None:
        with pytest.raises(KeyError):
            unregister_fetcher("never-registered")


class TestRunFetcher:
    async def test_registered_fetcher_runs_with_context(self) -> None:
        """The acceptance path: user_id and days_back are plumbed through."""
        register_fetcher("fetch_orders", _orders)

        result = await run_fetcher(
            "fetch_orders", FetchContext(user_id="u1", days_back=14)
        )

        assert result == "orders for u1 (last 14 days)"

    async def test_unknown_fetcher_is_skipped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale fetch_function on a module row degrades, never raises."""
        import app.services.ai.fetchers as fetchers_module

        warned = MagicMock()
        monkeypatch.setattr(fetchers_module.logger, "warning", warned)

        result = await run_fetcher(
            "ghost-fetcher", FetchContext(user_id="u1")
        )

        assert result is None
        warned.assert_called_once()
        assert warned.call_args.kwargs.get("fetch_function") == "ghost-fetcher"

    async def test_failing_fetcher_is_skipped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fetcher crash degrades that one module, never the turn."""
        import app.services.ai.fetchers as fetchers_module

        warned = MagicMock()
        monkeypatch.setattr(fetchers_module.logger, "warning", warned)

        async def boom(ctx: FetchContext) -> str | None:
            """Always fails."""
            raise RuntimeError("db exploded")

        register_fetcher("boom", boom)

        result = await run_fetcher("boom", FetchContext(user_id="u1"))

        assert result is None
        warned.assert_called_once()
        assert warned.call_args.kwargs.get("fetch_function") == "boom"
