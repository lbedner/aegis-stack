"""Tests for the payee icon domain guess and the durable icon store.

The upstream fetch itself is never exercised - a test that depends on it
would be testing Google's uptime, not this code. Everything around it is:
the domain guess (pure), and the read path's contract that a request
never waits on the network (DB hit serves, miss schedules a background
fill and returns nothing).
"""

from datetime import timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger import merchant_icon
from app.services.finance.domains.ledger.merchant_icon import merchant_icon_domain
from app.services.finance.models import FinanceIcon
from app.services.finance.utils import utcnow


class TestMerchantIconDomain:
    def test_clean_name_guesses_a_plausible_domain(self) -> None:
        assert merchant_icon_domain("Netflix") == "netflix.com"

    def test_punctuation_and_spacing_collapse_out(self) -> None:
        assert merchant_icon_domain("AT&T") == "att.com"

    def test_multi_word_name_joins_with_no_separator(self) -> None:
        assert merchant_icon_domain("State Farm") == "statefarm.com"

    def test_empty_input_has_nothing_to_guess_from(self) -> None:
        assert merchant_icon_domain("") is None
        assert merchant_icon_domain(None) is None

    def test_single_character_is_too_short_to_guess(self) -> None:
        assert merchant_icon_domain("$") is None

    def test_a_bank_descriptor_is_too_long_to_be_a_brand(self) -> None:
        """A finance-charge line is not a merchant, and guessing a domain
        from it can only ever miss - so it never costs a fetch."""
        assert merchant_icon_domain("INTEREST CHARGED TO PUR PR-11/28/25.") is None


class TestIconStore:
    """The read path never fetches: DB rows serve, misses only schedule."""

    @pytest.fixture(autouse=True)
    def _clean_slate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(merchant_icon, "_CACHE", {})
        monkeypatch.setattr(merchant_icon, "_IN_FLIGHT", set())

    @pytest.fixture
    def scheduled(self, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        calls: list[list[str]] = []
        monkeypatch.setattr(
            merchant_icon, "_schedule_fill", lambda domains: calls.append(domains)
        )
        return calls

    async def test_stored_icon_serves_from_db_without_a_fetch(
        self, async_db_session: AsyncSession, scheduled: list[list[str]]
    ) -> None:
        async_db_session.add(FinanceIcon(domain="netflix.com", icon_b64="abc123"))
        await async_db_session.flush()

        icons = await merchant_icon.icons_for_names(async_db_session, ["Netflix"])

        assert icons == {"Netflix": "abc123"}
        assert scheduled == []

    async def test_unknown_domain_returns_nothing_and_schedules_a_fill(
        self, async_db_session: AsyncSession, scheduled: list[list[str]]
    ) -> None:
        icons = await merchant_icon.icons_for_names(async_db_session, ["Netflix"])

        assert icons == {}
        assert scheduled == [["netflix.com"]]

    async def test_fresh_negative_row_suppresses_a_refetch(
        self, async_db_session: AsyncSession, scheduled: list[list[str]]
    ) -> None:
        async_db_session.add(FinanceIcon(domain="netflix.com", icon_b64=None))
        await async_db_session.flush()

        icons = await merchant_icon.icons_for_names(async_db_session, ["Netflix"])

        assert icons == {}
        assert scheduled == []

    async def test_stale_negative_row_is_retried(
        self, async_db_session: AsyncSession, scheduled: list[list[str]]
    ) -> None:
        stale = utcnow() - timedelta(days=8)
        async_db_session.add(
            FinanceIcon(domain="netflix.com", icon_b64=None, fetched_at=stale)
        )
        await async_db_session.flush()

        icons = await merchant_icon.icons_for_names(async_db_session, ["Netflix"])

        assert icons == {}
        assert scheduled == [["netflix.com"]]

    async def test_fill_persists_results_and_serves_next_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_fetch(domains: list[str]) -> dict[str, str | None]:
            return {"netflix.com": "xyz789", "unknowable.com": None}

        monkeypatch.setattr(merchant_icon, "_fetch_domains", fake_fetch)
        await merchant_icon._fill_icons(["netflix.com", "unknowable.com"])

        assert merchant_icon._CACHE["netflix.com"] == "xyz789"
        assert merchant_icon._CACHE["unknowable.com"] is None

        # The rows outlive the process-local cache: a cold process (empty
        # memory cache) still serves without scheduling anything.
        monkeypatch.setattr(merchant_icon, "_CACHE", {})
        calls: list[list[str]] = []
        monkeypatch.setattr(
            merchant_icon, "_schedule_fill", lambda domains: calls.append(domains)
        )
        from app.core.db import get_async_session

        async with get_async_session() as db:
            icons = await merchant_icon.icons_for_names(db, ["Netflix", "Unknowable"])
        assert icons == {"Netflix": "xyz789"}
        assert calls == []

    async def test_fill_refreshes_an_expired_negative_row(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core.db import get_async_session

        stale = utcnow() - timedelta(days=8)
        async with get_async_session() as db:
            db.add(
                FinanceIcon(domain="lateblooming.com", icon_b64=None, fetched_at=stale)
            )

        async def fake_fetch(domains: list[str]) -> dict[str, str | None]:
            return {"lateblooming.com": "found-at-last"}

        monkeypatch.setattr(merchant_icon, "_fetch_domains", fake_fetch)
        await merchant_icon._fill_icons(["lateblooming.com"])

        monkeypatch.setattr(merchant_icon, "_CACHE", {})
        monkeypatch.setattr(merchant_icon, "_schedule_fill", lambda domains: None)
        async with get_async_session() as db:
            icons = await merchant_icon.icons_for_names(db, ["Late Blooming"])
        assert icons == {"Late Blooming": "found-at-last"}
