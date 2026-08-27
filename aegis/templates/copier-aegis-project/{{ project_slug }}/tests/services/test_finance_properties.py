"""Property metadata: the Pydantic contract stored on a property account.

Real estate is an account (``account_type='property'``) wearing metadata,
the same shape goals and envelopes use - no new tables. The model IS the
validation boundary: a bad figure must fail on the way in, not sit in JSON
where every later reader has to re-guess it.
"""

from datetime import date

from typing import Any

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.ledger.properties import (
    PROPERTY_ACCOUNT_TYPE,
    PROPERTY_KINDS,
    VALUATION_SOURCES,
    PropertyMeta,
    clear_property_metadata,
    property_metadata,
    secured_position,
    set_property_metadata,
)
from app.services.finance.models import FinanceLiabilityDetail
from app.services.finance.service import FinanceService


def _stored() -> dict[str, object]:
    return set_property_metadata(
        None,
        purchase_price=28_500_000,
        purchase_date=date(2016, 8, 1),
        down_payment=5_700_000,
        property_kind="primary",
        valuation_source="user",
        valuation_as_of=date(2026, 8, 1),
        address_label="House Bedner",
    )


class TestRoundTrip:
    def test_stored_blob_parses_back_to_the_model(self) -> None:
        meta = property_metadata(_stored())

        assert meta is not None
        assert meta.purchase_price == 28_500_000
        assert meta.purchase_date == date(2016, 8, 1)
        assert meta.down_payment == 5_700_000
        assert meta.property_kind == "primary"
        assert meta.valuation_source == "user"
        assert meta.address_label == "House Bedner"

    def test_keys_are_namespaced_so_neighbours_survive(self) -> None:
        stored = set_property_metadata({"unrelated": 1}, purchase_price=1)

        assert stored["unrelated"] == 1
        assert all(key.startswith("property_") for key in stored if key != "unrelated")

    def test_clear_strips_only_the_property_keys(self) -> None:
        stored = {**_stored(), "unrelated": 1}

        remaining = clear_property_metadata(stored)

        assert remaining == {"unrelated": 1}

    def test_defaults_are_conservative(self) -> None:
        meta = property_metadata(set_property_metadata(None, purchase_price=1))

        assert meta is not None
        assert meta.include_in_net_worth is True
        assert meta.ownership_share_bps == 10_000  # wholly owned
        assert meta.valuation_source == "user"
        assert meta.property_kind == "primary"


class TestPresence:
    def test_an_account_without_property_keys_has_no_metadata(self) -> None:
        assert property_metadata({}) is None
        assert property_metadata(None) is None
        assert property_metadata({"goal_target_amount": 5}) is None

    def test_the_kind_key_is_the_presence_marker(self) -> None:
        """Purchase price is optional - a house you inherited has none -
        so presence cannot hang on it."""
        assert property_metadata({"property_kind": "primary"}) is not None


class TestValidation:
    def test_negative_purchase_price_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_property_metadata(None, purchase_price=-1)

    def test_unknown_valuation_source_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_property_metadata(None, purchase_price=1, valuation_source="vibes")

    def test_unknown_property_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_property_metadata(None, purchase_price=1, property_kind="spaceship")

    def test_ownership_share_over_one_hundred_percent_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            set_property_metadata(None, purchase_price=1, ownership_share_bps=10_001)

    def test_down_payment_above_purchase_price_is_rejected(self) -> None:
        """A down payment larger than the price is a data-entry slip that
        would silently distort every equity figure derived from it."""
        with pytest.raises(ValueError):
            set_property_metadata(None, purchase_price=100, down_payment=101)

    def test_corrupt_stored_source_fails_loudly_on_read(self) -> None:
        with pytest.raises(ValueError):
            property_metadata(
                {"property_kind": "primary", "property_valuation_source": "vibes"}
            )


class TestConstants:
    def test_the_account_type_matches_the_rows_already_in_the_ledger(self) -> None:
        assert PROPERTY_ACCOUNT_TYPE == "property"

    def test_the_vocabularies_are_closed(self) -> None:
        assert set(VALUATION_SOURCES) == {"user", "automated", "broker", "appraisal"}
        assert "primary" in PROPERTY_KINDS and "rental" in PROPERTY_KINDS


class TestModelIsFrozen:
    def test_a_parsed_meta_cannot_be_mutated(self) -> None:
        meta = property_metadata(_stored())
        assert meta is not None

        with pytest.raises(Exception):
            meta.purchase_price = 1  # type: ignore[misc]

    def test_the_model_serializes_by_alias(self) -> None:
        blob = PropertyMeta(property_kind="primary").model_dump(
            mode="json", by_alias=True
        )

        assert "property_kind" in blob


class TestPartialWrites:
    """The dialog shows six of the nine fields. A write that sent defaults
    for the other three would silently reset them - an address label typed
    once would vanish the next time anything else was saved."""

    @pytest.mark.asyncio
    async def test_an_unsent_field_keeps_its_stored_value(
        self, svc: FinanceService
    ) -> None:
        account = await svc.create_manual_account(
            name="House Bedner",
            account_type=PROPERTY_ACCOUNT_TYPE,
            classification="asset",
            owner_user_id=1,
        )
        await svc.set_property_details(
            account.id,
            owner_user_id=1,
            address_label="House Bedner",
            ownership_share_bps=5_000,
            include_in_net_worth=False,
        )

        await svc.set_property_details(
            account.id, owner_user_id=1, purchase_price=28_500_000
        )

        meta = property_metadata(account.metadata_)
        assert meta is not None
        assert meta.purchase_price == 28_500_000  # the write landed
        assert meta.address_label == "House Bedner"  # and took nothing with it
        assert meta.ownership_share_bps == 5_000
        assert meta.include_in_net_worth is False

    @pytest.mark.asyncio
    async def test_false_is_a_value_not_an_omission(self, svc: FinanceService) -> None:
        account = await svc.create_manual_account(
            name="Land",
            account_type=PROPERTY_ACCOUNT_TYPE,
            classification="asset",
            owner_user_id=1,
        )
        await svc.set_property_details(account.id, owner_user_id=1)

        await svc.set_property_details(
            account.id, owner_user_id=1, include_in_net_worth=False
        )

        meta = property_metadata(account.metadata_)
        assert meta is not None
        assert meta.include_in_net_worth is False


class TestServiceWrite:
    """Writing property facts through the service, on a real account row."""

    @pytest.mark.asyncio
    async def test_set_property_details_writes_and_reads_back(
        self, svc: FinanceService
    ) -> None:
        account = await svc.create_manual_account(
            name="House Bedner",
            account_type=PROPERTY_ACCOUNT_TYPE,
            classification="asset",
            owner_user_id=1,
            current_balance=71_120_000,
        )

        updated = await svc.set_property_details(
            account.id,
            owner_user_id=1,
            purchase_price=28_500_000,
            purchase_date=date(2016, 8, 1),
            down_payment=5_700_000,
            valuation_source="user",
            valuation_as_of=date(2026, 8, 1),
        )

        assert updated is not None
        meta = property_metadata(updated.metadata_)
        assert meta is not None
        assert meta.purchase_price == 28_500_000
        assert meta.valuation_source == "user"

    @pytest.mark.asyncio
    async def test_a_bad_figure_never_reaches_the_row(
        self, svc: FinanceService, async_db_session
    ) -> None:
        account = await svc.create_manual_account(
            name="House Bedner",
            account_type=PROPERTY_ACCOUNT_TYPE,
            classification="asset",
            owner_user_id=1,
        )

        with pytest.raises(ValueError):
            await svc.set_property_details(
                account.id, owner_user_id=1, valuation_source="vibes"
            )

        await async_db_session.refresh(account)
        assert property_metadata(account.metadata_) is None

    @pytest.mark.asyncio
    async def test_a_non_property_account_is_refused(self, svc: FinanceService) -> None:
        """Property facts on a checking account would sail through the JSON
        column and land in every net-worth reader downstream."""

        account = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )

        with pytest.raises(ValueError):
            await svc.set_property_details(account.id, owner_user_id=1)


class TestSecuredDebt:
    """FW-04: the ledger stores which property secures a liability (what
    the user confirms - lien priority is never inferred), and equity/LTV
    are derived from the link, computed and never stored."""

    def test_equity_and_ltv_derive_from_the_linked_balances(self) -> None:
        position = secured_position(71_120_000, [18_700_000])
        assert position is not None
        assert position.equity == 52_420_000
        assert position.ltv_bps == 2629  # 26.29%

    def test_a_second_lien_stacks_into_both_figures(self) -> None:
        position = secured_position(71_120_000, [18_700_000, 3_000_000])
        assert position is not None
        assert position.equity == 49_420_000
        assert position.ltv_bps == 3051

    def test_no_linked_liens_means_no_figures(self) -> None:
        """The gate's unlink case: removing the link removes the derived
        numbers entirely, it does not leave 100%-equity noise."""
        assert secured_position(71_120_000, []) is None

    def test_a_worthless_property_has_no_ratio(self) -> None:
        position = secured_position(0, [18_700_000])
        assert position is not None
        assert position.equity == -18_700_000
        assert position.ltv_bps is None

    @pytest.mark.asyncio
    async def test_the_link_is_stored_on_the_liability_detail(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        house = await svc.create_manual_account(
            name="House Bedner",
            account_type=PROPERTY_ACCOUNT_TYPE,
            classification="asset",
            owner_user_id=1,
        )
        mortgage = await svc.create_manual_account(
            name="Citizens Mortgage",
            account_type="loan",
            classification="liability",
            owner_user_id=1,
        )
        detail = FinanceLiabilityDetail(
            account_id=mortgage.id,
            secured_by_account_id=house.id,
            lien_position=1,
        )
        async_db_session.add(detail)
        await async_db_session.flush()

        assert detail.secured_by_account_id == house.id
        assert detail.lien_position == 1


class TestSecuredDebtService:
    """The write path stores only what the user confirms, and refuses
    links that cannot mean anything (a checking account "securing" a
    loan, a lien on an asset that is not a property)."""

    @staticmethod
    async def _pair(svc: FinanceService) -> tuple[Any, Any]:
        house = await svc.create_manual_account(
            name="House Bedner",
            account_type=PROPERTY_ACCOUNT_TYPE,
            classification="asset",
            owner_user_id=1,
        )
        mortgage = await svc.create_manual_account(
            name="Citizens Mortgage",
            account_type="loan",
            classification="liability",
            owner_user_id=1,
        )
        return house, mortgage

    @pytest.mark.asyncio
    async def test_link_then_unlink_round_trips(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        house, mortgage = await self._pair(svc)

        detail = await svc.set_secured_debt(
            mortgage.id,
            owner_user_id=1,
            secured_by_account_id=house.id,
            lien_position=1,
        )
        assert detail.secured_by_account_id == house.id
        assert detail.lien_position == 1

        linked_at = detail.updated_at

        detail = await svc.set_secured_debt(
            mortgage.id, owner_user_id=1, secured_by_account_id=None
        )
        assert detail.secured_by_account_id is None
        assert detail.lien_position is None
        # The row must LOOK changed: sync reconciliation and audit reads
        # trust updated_at, and a silent write hides the unlink from both.
        assert detail.updated_at > linked_at

    @pytest.mark.asyncio
    async def test_only_a_property_can_secure(self, svc: FinanceService) -> None:
        _, mortgage = await self._pair(svc)
        checking = await svc.create_manual_account(
            name="Checking",
            account_type="checking",
            classification="asset",
            owner_user_id=1,
        )
        with pytest.raises(ValueError):
            await svc.set_secured_debt(
                mortgage.id,
                owner_user_id=1,
                secured_by_account_id=checking.id,
                lien_position=1,
            )

    @pytest.mark.asyncio
    async def test_only_a_liability_can_be_secured(self, svc: FinanceService) -> None:
        house, _ = await self._pair(svc)
        with pytest.raises(ValueError):
            await svc.set_secured_debt(
                house.id,
                owner_user_id=1,
                secured_by_account_id=house.id,
                lien_position=1,
            )
