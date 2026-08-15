"""Tests for the finance reference-data models (currencies, FX rates).

Plain ``.py`` (not ``.jinja``): the ``import app.services.finance.models``
only resolves in finance-selected stacks, and those are the only stacks that
generate the package (non-finance stacks prune this file via the finance
FileManifest). Runs against the in-memory SQLite session from conftest, which
enforces foreign keys (``PRAGMA foreign_keys=ON``), so FK/unique/CHECK
violations surface here exactly as they would on Postgres.
"""

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import (
    FinanceConnection,
    FinanceCurrency,
    FinanceFxRate,
    FinanceInstitution,
    FinanceWebhookEvent,
)


async def _seed_currency(
    session: AsyncSession, code: str = "usd", *, decimals: int = 2, kind: str = "fiat"
) -> FinanceCurrency:
    currency = FinanceCurrency(
        code=code, name=code.upper(), decimals=decimals, kind=kind
    )
    session.add(currency)
    await session.flush()
    return currency


class TestFinanceCurrency:
    @pytest.mark.asyncio
    async def test_round_trips(self, async_db_session: AsyncSession) -> None:
        await _seed_currency(async_db_session, "usd")
        await async_db_session.commit()

        row = (
            await async_db_session.exec(
                select(FinanceCurrency).where(FinanceCurrency.code == "usd")
            )
        ).one()
        assert row.id is not None
        assert row.decimals == 2
        assert row.kind == "fiat"
        assert row.is_active is True

    @pytest.mark.asyncio
    async def test_code_is_unique(self, async_db_session: AsyncSession) -> None:
        # Add both rows, then flush once so the duplicate surfaces at the
        # assertion (a per-add flush would raise inside the seed helper).
        async_db_session.add(FinanceCurrency(code="usd", name="USD", decimals=2))
        async_db_session.add(FinanceCurrency(code="usd", name="USD dup", decimals=2))
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_kind_check_constraint(self, async_db_session: AsyncSession) -> None:
        async_db_session.add(
            FinanceCurrency(code="xxx", name="XXX", decimals=2, kind="bogus")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceFxRate:
    @pytest.mark.asyncio
    async def test_round_trips_with_fk(self, async_db_session: AsyncSession) -> None:
        await _seed_currency(async_db_session, "usd")
        await _seed_currency(async_db_session, "eur")
        rate = FinanceFxRate(
            base_currency="usd",
            quote_currency="eur",
            rate_date=date(2026, 7, 4),
            rate_e8=92_000_000,  # 0.92 EUR per USD, scaled by 1e8
        )
        async_db_session.add(rate)
        await async_db_session.commit()

        row = (await async_db_session.exec(select(FinanceFxRate))).one()
        assert row.rate_e8 == 92_000_000
        assert row.source == "manual"

    @pytest.mark.asyncio
    async def test_fk_requires_existing_currency(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceFxRate(
                base_currency="usd",
                quote_currency="nope",  # not a currency row
                rate_date=date(2026, 7, 4),
                rate_e8=1,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_base_and_quote_must_differ(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceFxRate(
                base_currency="usd",
                quote_currency="usd",
                rate_date=date(2026, 7, 4),
                rate_e8=100_000_000,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


# ---------------------------------------------------------------------------
# Group A — connections & sync
# ---------------------------------------------------------------------------


async def _seed_institution(
    session: AsyncSession, provider: str = "plaid", ext_id: str | None = "ins_1"
) -> FinanceInstitution:
    inst = FinanceInstitution(
        provider=provider, provider_institution_id=ext_id, name="Chase"
    )
    session.add(inst)
    await session.flush()
    return inst


class TestFinanceInstitution:
    @pytest.mark.asyncio
    async def test_round_trips(self, async_db_session: AsyncSession) -> None:
        inst = FinanceInstitution(
            provider="plaid",
            provider_institution_id="ins_56",
            name="American Express",
            supported_products=["transactions", "balance"],
            oauth_required=True,
        )
        async_db_session.add(inst)
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceInstitution))).one()
        assert row.supported_products == ["transactions", "balance"]
        assert row.oauth_required is True
        assert row.uses_tokenized_account_numbers is False

    @pytest.mark.asyncio
    async def test_provider_check_constraint(
        self, async_db_session: AsyncSession
    ) -> None:
        async_db_session.add(FinanceInstitution(provider="bogus", name="X"))
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_partial_unique_ext_id(self, async_db_session: AsyncSession) -> None:
        # Same (provider, ext_id) with a non-null ext_id collides...
        async_db_session.add(
            FinanceInstitution(
                provider="plaid", provider_institution_id="ins_dup", name="A"
            )
        )
        async_db_session.add(
            FinanceInstitution(
                provider="plaid", provider_institution_id="ins_dup", name="B"
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_null_ext_ids_do_not_collide(
        self, async_db_session: AsyncSession
    ) -> None:
        # ...but the partial index skips NULL ext_ids, so two are allowed.
        async_db_session.add(
            FinanceInstitution(
                provider="manual", provider_institution_id=None, name="A"
            )
        )
        async_db_session.add(
            FinanceInstitution(
                provider="manual", provider_institution_id=None, name="B"
            )
        )
        await async_db_session.flush()  # no IntegrityError


class TestFinanceConnection:
    @pytest.mark.asyncio
    async def test_round_trips(self, async_db_session: AsyncSession) -> None:
        inst = await _seed_institution(async_db_session)
        conn = FinanceConnection(
            owner_user_id=1,
            institution_id=inst.id,
            provider="plaid",
            connection_type="oauth_access_token",
            provider_item_id="item_abc",
            capabilities={"read_transactions": True},
        )
        async_db_session.add(conn)
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceConnection))).one()
        assert row.capabilities == {"read_transactions": True}
        assert row.status == "healthy"
        assert row.environment == "sandbox"

    @pytest.mark.asyncio
    async def test_repr_masks_credentials(self, async_db_session: AsyncSession) -> None:
        conn = FinanceConnection(
            provider="plaid",
            connection_type="oauth_access_token",
            access_token_encrypted="v2:supersecretciphertext",
        )
        text = repr(conn)
        assert "supersecretciphertext" not in text
        assert "access_token_encrypted" in text and "'***'" in text

    @pytest.mark.asyncio
    async def test_status_check_constraint(
        self, async_db_session: AsyncSession
    ) -> None:
        async_db_session.add(
            FinanceConnection(
                provider="plaid", connection_type="manual", status="banana"
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_partial_unique_provider_item_and_soft_delete(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import _utcnow

        first = FinanceConnection(
            provider="plaid",
            connection_type="oauth_access_token",
            provider_item_id="item_x",
        )
        async_db_session.add(first)
        await async_db_session.flush()

        # A second live connection for the same (provider, item) collides.
        dup = FinanceConnection(
            provider="plaid",
            connection_type="oauth_access_token",
            provider_item_id="item_x",
        )
        async_db_session.add(dup)
        with pytest.raises(IntegrityError):
            await async_db_session.flush()
        await async_db_session.rollback()

        # Soft-deleting the original releases the key (partial index excludes
        # deleted rows), so a fresh connection can reuse the item id.
        first = FinanceConnection(
            provider="plaid",
            connection_type="oauth_access_token",
            provider_item_id="item_y",
        )
        async_db_session.add(first)
        await async_db_session.flush()
        first.deleted_at = _utcnow()
        await async_db_session.flush()
        async_db_session.add(
            FinanceConnection(
                provider="plaid",
                connection_type="oauth_access_token",
                provider_item_id="item_y",
            )
        )
        await async_db_session.flush()  # no IntegrityError


class TestFinanceWebhookEvent:
    @pytest.mark.asyncio
    async def test_round_trips(self, async_db_session: AsyncSession) -> None:
        event = FinanceWebhookEvent(
            provider="plaid",
            webhook_type="TRANSACTIONS",
            webhook_code="SYNC_UPDATES_AVAILABLE",
            provider_event_id="evt_1",
            payload={"item_id": "item_abc"},
        )
        async_db_session.add(event)
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceWebhookEvent))).one()
        assert row.payload == {"item_id": "item_abc"}
        assert row.status == "received"

    @pytest.mark.asyncio
    async def test_event_id_is_idempotent(self, async_db_session: AsyncSession) -> None:
        async_db_session.add(
            FinanceWebhookEvent(provider="plaid", provider_event_id="evt_dup")
        )
        async_db_session.add(
            FinanceWebhookEvent(provider="plaid", provider_event_id="evt_dup")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


# ---------------------------------------------------------------------------
# Group B — accounts & balances
# ---------------------------------------------------------------------------


async def _seed_account(
    session: AsyncSession,
    *,
    owner: int | None = 1,
    account_type: str = "checking",
    classification: str = "asset",
    provider: str = "plaid",
    provider_account_id: str | None = None,
    is_manual: bool = False,
) -> "object":
    from app.services.finance.models import FinanceAccount

    await _seed_currency(session, "usd")
    acct = FinanceAccount(
        owner_user_id=owner,
        provider=provider,
        provider_account_id=provider_account_id,
        name="Chase Checking",
        account_type=account_type,
        classification=classification,
        is_manual=is_manual,
        current_balance=842_650,
    )
    session.add(acct)
    await session.flush()
    return acct


class TestFinanceAccount:
    @pytest.mark.asyncio
    async def test_round_trips(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceAccount

        await _seed_account(async_db_session)
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceAccount))).one()
        assert row.current_balance == 842_650
        assert row.classification == "asset"
        assert row.is_on_budget is True

    @pytest.mark.asyncio
    async def test_classification_check(self, async_db_session: AsyncSession) -> None:
        with pytest.raises(IntegrityError):
            await _seed_account(async_db_session, classification="banana")

    @pytest.mark.asyncio
    async def test_account_type_check(self, async_db_session: AsyncSession) -> None:
        with pytest.raises(IntegrityError):
            await _seed_account(async_db_session, account_type="spaceship")

    @pytest.mark.asyncio
    async def test_manual_account_no_connection(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceAccount

        await _seed_account(
            async_db_session,
            account_type="property",
            is_manual=True,
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceAccount))).one()
        assert row.connection_id is None
        assert row.is_manual is True


class TestFinanceBalanceSnapshot:
    @pytest.mark.asyncio
    async def test_round_trip_and_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceBalanceSnapshot

        acct = await _seed_account(async_db_session)
        async_db_session.add(
            FinanceBalanceSnapshot(
                account_id=acct.id,
                owner_user_id=1,
                balance_date=date(2026, 7, 4),
                balance=842_650,
            )
        )
        await async_db_session.flush()
        # One balance per account per day.
        async_db_session.add(
            FinanceBalanceSnapshot(
                account_id=acct.id,
                owner_user_id=1,
                balance_date=date(2026, 7, 4),
                balance=999,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_source_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceBalanceSnapshot

        acct = await _seed_account(async_db_session)
        async_db_session.add(
            FinanceBalanceSnapshot(
                account_id=acct.id,
                balance_date=date(2026, 7, 4),
                balance=1,
                source="telepathy",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceNetWorthSnapshot:
    @pytest.mark.asyncio
    async def test_round_trip_and_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceNetWorthSnapshot

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceNetWorthSnapshot(
                owner_user_id=1,
                as_of_date=date(2026, 7, 4),
                total_assets_amount=15_216_220,
                total_liabilities_amount=310_401,
                net_worth_amount=14_905_819,
            )
        )
        await async_db_session.flush()
        async_db_session.add(
            FinanceNetWorthSnapshot(
                owner_user_id=1, as_of_date=date(2026, 7, 4), net_worth_amount=0
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceValuation:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceValuation

        acct = await _seed_account(
            async_db_session, account_type="property", is_manual=True
        )
        async_db_session.add(
            FinanceValuation(
                owner_user_id=1,
                account_id=acct.id,
                as_of_date=date(2026, 7, 1),
                value=50_500_000,
                source="zillow",
                source_ref="https://zillow.com/x",
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceValuation))).one()
        assert row.value == 50_500_000
        assert row.source == "zillow"

    @pytest.mark.asyncio
    async def test_source_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceValuation

        acct = await _seed_account(async_db_session, is_manual=True)
        async_db_session.add(
            FinanceValuation(
                account_id=acct.id,
                as_of_date=date(2026, 7, 1),
                value=1,
                source="ouija",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceLiabilityDetail:
    @pytest.mark.asyncio
    async def test_round_trip_and_one_to_one(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceLiabilityDetail

        acct = await _seed_account(
            async_db_session, account_type="credit_card", classification="liability"
        )
        async_db_session.add(
            FinanceLiabilityDetail(
                owner_user_id=1,
                account_id=acct.id,
                liability_type="credit",
                minimum_payment_amount=3_500,
                interest_rate_bps=1999,
                aprs=[{"apr_type": "purchase", "apr_percentage_bps": 1999}],
            )
        )
        await async_db_session.flush()
        # 1:1 per account.
        async_db_session.add(
            FinanceLiabilityDetail(account_id=acct.id, liability_type="credit")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


# ---------------------------------------------------------------------------
# Group C (core) — transactions, splits, transfers
# ---------------------------------------------------------------------------


async def _seed_transaction(
    session: AsyncSession,
    *,
    owner: int | None = 1,
    source: str = "plaid",
    external_id: str | None = "ext_1",
    import_hash: str | None = None,
    amount: int = -4599,
    txn_date: date = date(2026, 7, 4),
    account: "object | None" = None,
) -> "object":
    from app.services.finance.models import FinanceTransaction

    if account is None:
        account = await _seed_account(session)
    txn = FinanceTransaction(
        owner_user_id=owner,
        account_id=account.id,
        source=source,
        external_id=external_id,
        import_hash=import_hash,
        amount=amount,
        date_=txn_date,
    )
    session.add(txn)
    await session.flush()
    return txn


class TestFinanceTransaction:
    @pytest.mark.asyncio
    async def test_round_trips(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransaction

        acct = await _seed_account(async_db_session)
        txn = FinanceTransaction(
            owner_user_id=1,
            account_id=acct.id,
            source="plaid",
            external_id="txn_abc",
            amount=-4599,  # $45.99 outflow, integer minor units
            raw_amount=4599,
            date_=date(2026, 7, 4),
            datetime_=None,
            name="Blue Bottle Coffee",
            location={"city": "Oakland", "region": "CA"},
            counterparties=[{"name": "Blue Bottle", "type": "merchant"}],
            raw_payload={"transaction_id": "txn_abc"},
            metadata_={"note": "morning"},
        )
        async_db_session.add(txn)
        await async_db_session.commit()

        row = (await async_db_session.exec(select(FinanceTransaction))).one()
        assert row.amount == -4599
        assert row.raw_amount == 4599
        assert row.date_ == date(2026, 7, 4)
        assert row.location == {"city": "Oakland", "region": "CA"}
        assert row.counterparties == [{"name": "Blue Bottle", "type": "merchant"}]
        assert row.raw_payload == {"transaction_id": "txn_abc"}
        assert row.metadata_ == {"note": "morning"}
        # Defaults.
        assert row.status == "posted"
        assert row.dedup_status == "unique"
        assert row.category_source == "unset"
        assert row.reconciled_status == "uncleared"
        assert row.pending is False
        assert row.currency == "usd"

    @pytest.mark.asyncio
    async def test_source_check(self, async_db_session: AsyncSession) -> None:
        with pytest.raises(IntegrityError):
            await _seed_transaction(async_db_session, source="carrier_pigeon")

    @pytest.mark.asyncio
    async def test_status_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransaction

        acct = await _seed_account(async_db_session)
        async_db_session.add(
            FinanceTransaction(
                account_id=acct.id,
                source="plaid",
                amount=-1,
                date_=date(2026, 7, 4),
                status="in_the_mail",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_dedup_lane_forbids_both_ids(
        self, async_db_session: AsyncSession
    ) -> None:
        # A row belongs to exactly one dedup lane: a provider external_id OR an
        # import_hash, never both (ck_finance_txn_dedup_lane).
        with pytest.raises(IntegrityError):
            await _seed_transaction(
                async_db_session, external_id="ext_1", import_hash="hash_1"
            )

    @pytest.mark.asyncio
    async def test_partial_unique_external_and_soft_delete(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceTransaction, _utcnow

        acct = await _seed_account(async_db_session)
        first = await _seed_transaction(
            async_db_session, external_id="dup_ext", account=acct
        )

        # LANE 1: same (account, source, external_id) collides.
        dup = FinanceTransaction(
            account_id=acct.id,
            source="plaid",
            external_id="dup_ext",
            amount=-1,
            date_=date(2026, 7, 4),
        )
        async_db_session.add(dup)
        with pytest.raises(IntegrityError):
            await async_db_session.flush()
        await async_db_session.rollback()

        # Soft-deleting the original releases the key (partial index excludes
        # soft-deleted rows).
        acct = await _seed_account(async_db_session)
        first = await _seed_transaction(
            async_db_session, external_id="reuse_ext", account=acct
        )
        first.deleted_at = _utcnow()
        await async_db_session.flush()
        async_db_session.add(
            FinanceTransaction(
                account_id=acct.id,
                source="plaid",
                external_id="reuse_ext",
                amount=-1,
                date_=date(2026, 7, 4),
            )
        )
        await async_db_session.flush()  # no IntegrityError

    @pytest.mark.asyncio
    async def test_partial_unique_import_hash(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceTransaction

        acct = await _seed_account(async_db_session)
        # LANE 2: file imports with no external_id dedup on (account, hash).
        async_db_session.add(
            FinanceTransaction(
                account_id=acct.id,
                source="csv",
                external_id=None,
                import_hash="row_hash",
                amount=-100,
                date_=date(2026, 7, 4),
            )
        )
        await async_db_session.flush()
        async_db_session.add(
            FinanceTransaction(
                account_id=acct.id,
                source="csv",
                external_id=None,
                import_hash="row_hash",
                amount=-100,
                date_=date(2026, 7, 4),
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_null_dedup_keys_do_not_collide(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceTransaction

        acct = await _seed_account(async_db_session)
        # Both partial indexes skip rows with no external_id and no hash (e.g.
        # hand-entered), so two such rows coexist.
        for _ in range(2):
            async_db_session.add(
                FinanceTransaction(
                    account_id=acct.id,
                    source="manual",
                    external_id=None,
                    import_hash=None,
                    amount=-1,
                    date_=date(2026, 7, 4),
                )
            )
        await async_db_session.flush()  # no IntegrityError

    @pytest.mark.asyncio
    async def test_self_fk_pending_link(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransaction

        acct = await _seed_account(async_db_session)
        posted = await _seed_transaction(
            async_db_session, external_id="posted_1", account=acct
        )
        # A pending row can point at the posted row it will settle into.
        pending = FinanceTransaction(
            account_id=acct.id,
            source="plaid",
            external_id="pending_1",
            amount=-4599,
            date_=date(2026, 7, 4),
            pending=True,
            pending_transaction_id=posted.id,
        )
        async_db_session.add(pending)
        await async_db_session.flush()
        assert pending.pending_transaction_id == posted.id

        # A dangling self-FK is rejected.
        async_db_session.add(
            FinanceTransaction(
                account_id=acct.id,
                source="plaid",
                external_id="pending_2",
                amount=-1,
                date_=date(2026, 7, 4),
                pending_transaction_id=999_999,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceTransactionSplit:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransactionSplit

        parent = await _seed_transaction(async_db_session)
        async_db_session.add(
            FinanceTransactionSplit(
                owner_user_id=1,
                parent_transaction_id=parent.id,
                amount=-3000,
                sort_order=0,
                memo="groceries",
            )
        )
        async_db_session.add(
            FinanceTransactionSplit(
                owner_user_id=1,
                parent_transaction_id=parent.id,
                amount=-1599,
                sort_order=1,
                memo="household",
            )
        )
        await async_db_session.commit()
        rows = (await async_db_session.exec(select(FinanceTransactionSplit))).all()
        assert len(rows) == 2
        assert sum(r.amount for r in rows) == -4599  # sums to parent

    @pytest.mark.asyncio
    async def test_parent_fk_required(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransactionSplit

        await _seed_account(async_db_session)  # currency, but no such parent txn
        async_db_session.add(
            FinanceTransactionSplit(parent_transaction_id=999_999, amount=-1)
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_unique_parent_sort(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransactionSplit

        parent = await _seed_transaction(async_db_session)
        async_db_session.add(
            FinanceTransactionSplit(
                parent_transaction_id=parent.id, amount=-1, sort_order=0
            )
        )
        async_db_session.add(
            FinanceTransactionSplit(
                parent_transaction_id=parent.id, amount=-2, sort_order=0
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceTransfer:
    async def _seed_pair(
        self, session: AsyncSession
    ) -> "tuple[object, object, object, object]":
        from app.services.finance.models import FinanceAccount, FinanceTransaction

        acct1 = await _seed_account(session)  # checking asset (seeds usd)
        acct2 = FinanceAccount(
            owner_user_id=1,
            provider="plaid",
            name="AMEX",
            account_type="credit_card",
            classification="liability",
        )
        session.add(acct2)
        await session.flush()
        t_from = FinanceTransaction(
            owner_user_id=1,
            account_id=acct1.id,
            source="plaid",
            external_id="pay_out",
            amount=-25000,
            date_=date(2026, 7, 4),
        )
        t_to = FinanceTransaction(
            owner_user_id=1,
            account_id=acct2.id,
            source="plaid",
            external_id="pay_in",
            amount=25000,
            date_=date(2026, 7, 4),
        )
        session.add(t_from)
        session.add(t_to)
        await session.flush()
        return acct1, acct2, t_from, t_to

    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransfer

        acct1, acct2, t_from, t_to = await self._seed_pair(async_db_session)
        transfer = FinanceTransfer(
            owner_user_id=1,
            from_account_id=acct1.id,
            to_account_id=acct2.id,
            from_transaction_id=t_from.id,
            to_transaction_id=t_to.id,
            amount=25000,
            match_method="auto_amount_date",
            is_credit_card_payment=True,
        )
        async_db_session.add(transfer)
        await async_db_session.commit()

        row = (await async_db_session.exec(select(FinanceTransfer))).one()
        assert row.status == "suggested"
        assert row.is_credit_card_payment is True
        assert row.amount == 25000

    @pytest.mark.asyncio
    async def test_match_method_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransfer

        await self._seed_pair(async_db_session)
        async_db_session.add(FinanceTransfer(match_method="vibes"))
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_from_leg_is_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransfer

        _, _, t_from, t_to = await self._seed_pair(async_db_session)
        async_db_session.add(
            FinanceTransfer(from_transaction_id=t_from.id, match_method="user_manual")
        )
        await async_db_session.flush()
        # A transaction leg maps to at most one transfer per direction.
        async_db_session.add(
            FinanceTransfer(from_transaction_id=t_from.id, match_method="user_manual")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_legs_must_differ(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransfer

        _, _, t_from, _ = await self._seed_pair(async_db_session)
        # A transfer cannot have the same transaction on both legs.
        async_db_session.add(
            FinanceTransfer(
                from_transaction_id=t_from.id,
                to_transaction_id=t_from.id,
                match_method="user_manual",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


# ---------------------------------------------------------------------------
# Group D (ref) — categories, merchants, tags, rules
# ---------------------------------------------------------------------------


async def _seed_category(
    session: AsyncSession,
    *,
    owner: int | None = None,
    slug: str = "dining",
    name: str = "Dining",
    classification: str = "expense",
) -> "object":
    from app.services.finance.models import FinanceCategory

    cat = FinanceCategory(
        owner_user_id=owner, slug=slug, name=name, classification=classification
    )
    session.add(cat)
    await session.flush()
    return cat


class TestFinanceCategory:
    @pytest.mark.asyncio
    async def test_round_trips_with_self_parent(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceCategory

        parent = await _seed_category(
            async_db_session, slug="food", name="Food & Drink"
        )
        child = FinanceCategory(
            slug="food.dining",
            name="Dining",
            classification="expense",
            parent_id=parent.id,
            plaid_pfc_detailed="FOOD_AND_DRINK_RESTAURANT",
        )
        async_db_session.add(child)
        await async_db_session.commit()
        row = (
            await async_db_session.exec(
                select(FinanceCategory).where(FinanceCategory.slug == "food.dining")
            )
        ).one()
        assert row.parent_id == parent.id
        assert row.is_system is False

    @pytest.mark.asyncio
    async def test_classification_check(self, async_db_session: AsyncSession) -> None:
        with pytest.raises(IntegrityError):
            await _seed_category(async_db_session, classification="spending")

    @pytest.mark.asyncio
    async def test_system_slug_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceCategory

        # Two system seeds (owner NULL) cannot share a slug. Add both, then
        # flush once so the duplicate surfaces at the assertion.
        async_db_session.add(
            FinanceCategory(slug="rent", name="Rent", classification="expense")
        )
        async_db_session.add(
            FinanceCategory(slug="rent", name="Rent 2", classification="expense")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_user_and_system_slug_coexist(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceCategory

        # The system partial index only covers owner NULL, so a user category
        # can reuse a system slug (scoped to the owner by the user index).
        async_db_session.add(
            FinanceCategory(slug="gifts", name="Gifts", classification="expense")
        )
        async_db_session.add(
            FinanceCategory(
                owner_user_id=7, slug="gifts", name="Gifts", classification="expense"
            )
        )
        async_db_session.add(
            FinanceCategory(
                owner_user_id=8, slug="gifts", name="Gifts", classification="expense"
            )
        )
        await async_db_session.flush()  # no IntegrityError
        # ...but the same user twice does collide.
        async_db_session.add(
            FinanceCategory(
                owner_user_id=7, slug="gifts", name="Dup", classification="expense"
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceCategoryAlias:
    @pytest.mark.asyncio
    async def test_round_trip_and_fk(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceCategoryAlias

        cat = await _seed_category(async_db_session, slug="dining")
        async_db_session.add(
            FinanceCategoryAlias(
                category_id=cat.id,
                alias_text="RESTAURANTS/DINING",
                normalized_alias="restaurants dining",
                source="quicken",
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceCategoryAlias))).one()
        assert row.category_id == cat.id
        assert row.normalized_alias == "restaurants dining"

    @pytest.mark.asyncio
    async def test_fk_requires_category(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceCategoryAlias

        async_db_session.add(
            FinanceCategoryAlias(
                category_id=999_999,
                alias_text="x",
                normalized_alias="x",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_owner_norm_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceCategoryAlias

        cat = await _seed_category(async_db_session, slug="dining")
        for _ in range(2):
            async_db_session.add(
                FinanceCategoryAlias(
                    owner_user_id=1,
                    category_id=cat.id,
                    alias_text="Dining",
                    normalized_alias="dining",
                )
            )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceMerchant:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceMerchant

        cat = await _seed_category(async_db_session, slug="subscriptions")
        async_db_session.add(
            FinanceMerchant(
                owner_user_id=1,
                name="Spotify",
                normalized_name="spotify",
                source="plaid",
                default_category_id=cat.id,
                service_type="music_streaming",
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceMerchant))).one()
        assert row.default_category_id == cat.id
        assert row.service_type == "music_streaming"

    @pytest.mark.asyncio
    async def test_source_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceMerchant

        async_db_session.add(
            FinanceMerchant(name="X", normalized_name="x", source="telepathy")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_user_partial_unique_and_soft_delete(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceMerchant, _utcnow

        first = FinanceMerchant(
            owner_user_id=1, name="Netflix", normalized_name="netflix", source="user"
        )
        async_db_session.add(first)
        await async_db_session.flush()
        dup = FinanceMerchant(
            owner_user_id=1, name="Netflix", normalized_name="netflix", source="user"
        )
        async_db_session.add(dup)
        with pytest.raises(IntegrityError):
            await async_db_session.flush()
        await async_db_session.rollback()

        # Soft-delete releases the normalized-name key.
        first = FinanceMerchant(
            owner_user_id=1, name="Hulu", normalized_name="hulu", source="user"
        )
        async_db_session.add(first)
        await async_db_session.flush()
        first.deleted_at = _utcnow()
        await async_db_session.flush()
        async_db_session.add(
            FinanceMerchant(
                owner_user_id=1, name="Hulu", normalized_name="hulu", source="user"
            )
        )
        await async_db_session.flush()  # no IntegrityError

    @pytest.mark.asyncio
    async def test_provider_partial_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceMerchant

        # Distinct names (so the global index doesn't fire) but the same
        # (source, provider_merchant_id) collides on the provider index.
        async_db_session.add(
            FinanceMerchant(
                name="Amazon",
                normalized_name="amazon",
                source="plaid",
                provider_merchant_id="mch_amzn",
            )
        )
        async_db_session.add(
            FinanceMerchant(
                name="Amazon Prime",
                normalized_name="amazon prime",
                source="plaid",
                provider_merchant_id="mch_amzn",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceTag:
    @pytest.mark.asyncio
    async def test_round_trip_and_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTag, _utcnow

        async_db_session.add(
            FinanceTag(owner_user_id=1, name="Vacation", normalized_name="vacation")
        )
        await async_db_session.flush()
        async_db_session.add(
            FinanceTag(owner_user_id=1, name="vacation", normalized_name="vacation")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()
        await async_db_session.rollback()

        # Soft-deleting frees the name for reuse.
        tag = FinanceTag(owner_user_id=1, name="Work", normalized_name="work")
        async_db_session.add(tag)
        await async_db_session.flush()
        tag.deleted_at = _utcnow()
        await async_db_session.flush()
        async_db_session.add(
            FinanceTag(owner_user_id=1, name="Work", normalized_name="work")
        )
        await async_db_session.flush()  # no IntegrityError


class TestFinanceTransactionTag:
    @pytest.mark.asyncio
    async def test_link_and_composite_pk(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import (
            FinanceTag,
            FinanceTransactionTag,
        )

        txn = await _seed_transaction(async_db_session)
        tag = FinanceTag(owner_user_id=1, name="Trip", normalized_name="trip")
        async_db_session.add(tag)
        await async_db_session.flush()

        async_db_session.add(
            FinanceTransactionTag(transaction_id=txn.id, tag_id=tag.id)
        )
        await async_db_session.flush()
        # Re-linking the same (transaction, tag) violates the composite PK.
        async_db_session.add(
            FinanceTransactionTag(transaction_id=txn.id, tag_id=tag.id)
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_fk_requires_transaction_and_tag(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceTransactionTag

        await _seed_account(async_db_session)
        async_db_session.add(
            FinanceTransactionTag(transaction_id=999_999, tag_id=999_999)
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceRule:
    @pytest.mark.asyncio
    async def test_round_trip_with_json(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceRule

        async_db_session.add(
            FinanceRule(
                owner_user_id=1,
                name="Rename Amazon",
                conditions={"payee_contains": "AMZN"},
                actions={"set_merchant": "Amazon"},
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceRule))).one()
        assert row.conditions == {"payee_contains": "AMZN"}
        assert row.actions == {"set_merchant": "Amazon"}
        assert row.priority == 100
        assert row.is_enabled is True


# ---------------------------------------------------------------------------
# Group E (investments) — securities, prices, holdings, trades
# ---------------------------------------------------------------------------


async def _seed_security(
    session: AsyncSession,
    *,
    provider: str = "plaid",
    provider_security_id: str | None = "sec_1",
    ticker: str = "AAPL",
    name: str = "Apple Inc.",
    security_type: str = "equity",
) -> "object":
    from app.services.finance.models import FinanceSecurity

    sec = FinanceSecurity(
        provider=provider,
        provider_security_id=provider_security_id,
        ticker=ticker,
        name=name,
        security_type=security_type,
    )
    session.add(sec)
    await session.flush()
    return sec


class TestFinanceSecurity:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceSecurity

        sec = FinanceSecurity(
            provider="plaid",
            provider_security_id="sec_aapl",
            figi="BBG000B9XRY4",
            cusip="037833100",
            ticker="AAPL",
            name="Apple Inc.",
            security_type="equity",
        )
        async_db_session.add(sec)
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceSecurity))).one()
        assert row.price_scale == 2
        assert row.is_crypto is False
        assert row.figi == "BBG000B9XRY4"

    @pytest.mark.asyncio
    async def test_provider_partial_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceSecurity

        async_db_session.add(
            FinanceSecurity(provider="plaid", provider_security_id="dup", ticker="A")
        )
        async_db_session.add(
            FinanceSecurity(provider="plaid", provider_security_id="dup", ticker="B")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_figi_partial_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceSecurity

        # Distinct provider ids so only the FIGI index fires.
        async_db_session.add(
            FinanceSecurity(provider="plaid", provider_security_id="p1", figi="FIGI1")
        )
        async_db_session.add(
            FinanceSecurity(
                provider="snaptrade", provider_security_id="p2", figi="FIGI1"
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_null_dedup_keys_coexist(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceSecurity

        # Manual securities with no provider/figi/cusip/isin don't collide.
        for _ in range(2):
            async_db_session.add(
                FinanceSecurity(provider="manual", ticker="PRIV", name="Private")
            )
        await async_db_session.flush()  # no IntegrityError


class TestFinanceSecurityPrice:
    @pytest.mark.asyncio
    async def test_round_trip_and_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceSecurityPrice

        await _seed_currency(async_db_session, "usd")
        sec = await _seed_security(async_db_session)
        async_db_session.add(
            FinanceSecurityPrice(
                security_id=sec.id,
                price_date=date(2026, 7, 4),
                close_price=21_450,  # $214.50
                source="market_data",
            )
        )
        await async_db_session.flush()
        # One price per security/day/source.
        async_db_session.add(
            FinanceSecurityPrice(
                security_id=sec.id,
                price_date=date(2026, 7, 4),
                close_price=99,
                source="market_data",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_source_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceSecurityPrice

        await _seed_currency(async_db_session, "usd")
        sec = await _seed_security(async_db_session)
        async_db_session.add(
            FinanceSecurityPrice(
                security_id=sec.id,
                price_date=date(2026, 7, 4),
                close_price=1,
                source="astrology",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceHolding:
    @pytest.mark.asyncio
    async def test_round_trip_and_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceHolding

        acct = await _seed_account(async_db_session, account_type="brokerage")
        sec = await _seed_security(async_db_session)
        async_db_session.add(
            FinanceHolding(
                owner_user_id=1,
                account_id=acct.id,
                security_id=sec.id,
                as_of_date=date(2026, 7, 4),
                quantity_e8=10_00000000,  # 10 shares
                cost_basis=150_000,
            )
        )
        await async_db_session.flush()
        # One position per (account, security, day).
        async_db_session.add(
            FinanceHolding(
                owner_user_id=1,
                account_id=acct.id,
                security_id=sec.id,
                as_of_date=date(2026, 7, 4),
                quantity_e8=1,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_security_fk_required(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceHolding

        acct = await _seed_account(async_db_session, account_type="brokerage")
        async_db_session.add(
            FinanceHolding(
                owner_user_id=1,
                account_id=acct.id,
                security_id=999_999,
                as_of_date=date(2026, 7, 4),
                quantity_e8=1,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceTrade:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTrade

        acct = await _seed_account(async_db_session, account_type="brokerage")
        sec = await _seed_security(async_db_session)
        async_db_session.add(
            FinanceTrade(
                owner_user_id=1,
                account_id=acct.id,
                security_id=sec.id,
                source="plaid",
                external_id="trade_1",
                type="buy",
                quantity_e8=5_00000000,  # 5 shares
                price=21_450,
                amount=-107_250,  # cash out
                trade_date=date(2026, 7, 4),
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceTrade))).one()
        assert row.amount == -107_250
        assert row.type == "buy"
        assert row.price_scale == 2
        assert row.pending is False

    @pytest.mark.asyncio
    async def test_type_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTrade

        acct = await _seed_account(async_db_session, account_type="brokerage")
        async_db_session.add(
            FinanceTrade(
                owner_user_id=1,
                account_id=acct.id,
                source="plaid",
                type="hodl",
                trade_date=date(2026, 7, 4),
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_dedup_lane_forbids_both_ids(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceTrade

        acct = await _seed_account(async_db_session, account_type="brokerage")
        async_db_session.add(
            FinanceTrade(
                owner_user_id=1,
                account_id=acct.id,
                source="csv",
                external_id="e1",
                import_hash="h1",
                type="buy",
                trade_date=date(2026, 7, 4),
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_external_partial_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceTrade

        acct = await _seed_account(async_db_session, account_type="brokerage")
        for _ in range(2):
            async_db_session.add(
                FinanceTrade(
                    owner_user_id=1,
                    account_id=acct.id,
                    source="plaid",
                    external_id="dup_trade",
                    type="buy",
                    trade_date=date(2026, 7, 4),
                )
            )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


# ---------------------------------------------------------------------------
# Group F (analytics / import) — recurring streams, budgets, baselines,
# insights, import pipeline, attachments, changelog
# ---------------------------------------------------------------------------


class TestFinanceRecurringStream:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceRecurringStream

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceRecurringStream(
                owner_user_id=1,
                name="Netflix",
                direction="outflow",
                frequency="monthly",
                source="plaid",
                is_subscription=True,
                average_amount=1599,
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceRecurringStream))).one()
        assert row.status == "early_detection"
        assert row.is_active is True
        assert row.is_subscription is True

    @pytest.mark.asyncio
    async def test_direction_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceRecurringStream

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceRecurringStream(
                owner_user_id=1,
                name="X",
                direction="sideways",
                frequency="monthly",
                source="plaid",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_detected_partial_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceRecurringStream

        acct = await _seed_account(async_db_session)
        # Locally-detected streams (no provider id) dedup on
        # (owner, account, direction, normalized_payee).
        for _ in range(2):
            async_db_session.add(
                FinanceRecurringStream(
                    owner_user_id=1,
                    account_id=acct.id,
                    name="Netflix",
                    normalized_payee="netflix",
                    direction="outflow",
                    frequency="monthly",
                    source="derived",
                )
            )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceBudget:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceBudget

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceBudget(
                owner_user_id=1,
                name="Monthly",
                period="monthly",
                start_date=date(2026, 7, 1),
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceBudget))).one()
        assert row.is_active is True
        assert row.rollover is False

    @pytest.mark.asyncio
    async def test_period_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceBudget

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceBudget(
                owner_user_id=1,
                name="X",
                period="hourly",
                start_date=date(2026, 7, 1),
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_owner_name_start_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceBudget

        await _seed_currency(async_db_session, "usd")
        for _ in range(2):
            async_db_session.add(
                FinanceBudget(
                    owner_user_id=1,
                    name="Monthly",
                    period="monthly",
                    start_date=date(2026, 7, 1),
                )
            )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceBudgetCategory:
    @pytest.mark.asyncio
    async def test_round_trip_and_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceBudget, FinanceBudgetCategory

        await _seed_currency(async_db_session, "usd")
        cat = await _seed_category(async_db_session, slug="dining")
        budget = FinanceBudget(
            owner_user_id=1,
            name="Monthly",
            period="monthly",
            start_date=date(2026, 7, 1),
        )
        async_db_session.add(budget)
        await async_db_session.flush()
        async_db_session.add(
            FinanceBudgetCategory(
                owner_user_id=1,
                budget_id=budget.id,
                category_id=cat.id,
                period_month=202607,
                allocated_amount=50_000,
            )
        )
        await async_db_session.flush()
        # One line per (budget, category, month).
        async_db_session.add(
            FinanceBudgetCategory(
                owner_user_id=1,
                budget_id=budget.id,
                category_id=cat.id,
                period_month=202607,
                allocated_amount=99,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_payee_target_coexists_with_category_target(
        self, async_db_session: AsyncSession
    ) -> None:
        """A category row and a payee row for the same budget/month are NOT
        duplicates of each other - the old 3-column unique index (NULL
        category_id on the payee row) would never have caught this anyway;
        the partial indexes make the intent explicit instead of accidental."""
        from app.services.finance.models import FinanceBudget, FinanceBudgetCategory

        await _seed_currency(async_db_session, "usd")
        cat = await _seed_category(async_db_session, slug="dining")
        budget = FinanceBudget(
            owner_user_id=1,
            name="Monthly",
            period="monthly",
            start_date=date(2026, 7, 1),
        )
        async_db_session.add(budget)
        await async_db_session.flush()
        async_db_session.add(
            FinanceBudgetCategory(
                owner_user_id=1,
                budget_id=budget.id,
                category_id=cat.id,
                period_month=202607,
                allocated_amount=50_000,
            )
        )
        async_db_session.add(
            FinanceBudgetCategory(
                owner_user_id=1,
                budget_id=budget.id,
                payee_key="starbucks",
                payee_label="Starbucks",
                period_month=202607,
                allocated_amount=5_000,
            )
        )
        await async_db_session.commit()
        rows = (
            await async_db_session.exec(
                select(FinanceBudgetCategory).where(
                    FinanceBudgetCategory.budget_id == budget.id
                )
            )
        ).all()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_payee_target_unique_per_month(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceBudget, FinanceBudgetCategory

        await _seed_currency(async_db_session, "usd")
        budget = FinanceBudget(
            owner_user_id=1,
            name="Monthly",
            period="monthly",
            start_date=date(2026, 7, 1),
        )
        async_db_session.add(budget)
        await async_db_session.flush()
        async_db_session.add(
            FinanceBudgetCategory(
                owner_user_id=1,
                budget_id=budget.id,
                payee_key="starbucks",
                payee_label="Starbucks",
                period_month=202607,
                allocated_amount=5_000,
            )
        )
        await async_db_session.flush()
        async_db_session.add(
            FinanceBudgetCategory(
                owner_user_id=1,
                budget_id=budget.id,
                payee_key="starbucks",
                payee_label="Starbucks",
                period_month=202607,
                allocated_amount=1,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_target_check_rejects_both_category_and_payee(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceBudget, FinanceBudgetCategory

        await _seed_currency(async_db_session, "usd")
        cat = await _seed_category(async_db_session, slug="dining")
        budget = FinanceBudget(
            owner_user_id=1,
            name="Monthly",
            period="monthly",
            start_date=date(2026, 7, 1),
        )
        async_db_session.add(budget)
        await async_db_session.flush()
        async_db_session.add(
            FinanceBudgetCategory(
                owner_user_id=1,
                budget_id=budget.id,
                category_id=cat.id,
                payee_key="starbucks",
                period_month=202607,
                allocated_amount=5_000,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceSpendingBaseline:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceSpendingBaseline

        await _seed_currency(async_db_session, "usd")
        cat = await _seed_category(async_db_session, slug="dining")
        async_db_session.add(
            FinanceSpendingBaseline(
                owner_user_id=1,
                category_id=cat.id,
                window_months=6,
                period_month=202607,
                trailing_avg_amount=42_000,
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceSpendingBaseline))).one()
        assert row.trailing_avg_amount == 42_000
        assert row.window_months == 6

    @pytest.mark.asyncio
    async def test_window_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceSpendingBaseline

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceSpendingBaseline(
                owner_user_id=1,
                window_months=5,  # only 3/6/12 allowed
                period_month=202607,
                trailing_avg_amount=1,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceInsight:
    @pytest.mark.asyncio
    async def test_round_trip_and_dedup(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceInsight

        async_db_session.add(
            FinanceInsight(
                owner_user_id=1,
                insight_type="price_hike",
                severity="warning",
                title="Netflix went up",
                dedup_key="price_hike:netflix:202607",
                data={"old": 1599, "new": 1899},
            )
        )
        await async_db_session.flush()
        assert (
            await async_db_session.exec(select(FinanceInsight))
        ).one().status == "new"
        # dedup_key is idempotent per owner.
        async_db_session.add(
            FinanceInsight(
                owner_user_id=1,
                insight_type="price_hike",
                severity="info",
                title="dup",
                dedup_key="price_hike:netflix:202607",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_severity_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceInsight

        async_db_session.add(
            FinanceInsight(
                owner_user_id=1,
                insight_type="x",
                severity="apocalyptic",
                title="x",
                dedup_key="x",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_related_stream_fk(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import (
            FinanceInsight,
            FinanceRecurringStream,
        )

        await _seed_currency(async_db_session, "usd")
        stream = FinanceRecurringStream(
            owner_user_id=1,
            name="Netflix",
            direction="outflow",
            frequency="monthly",
            source="plaid",
        )
        async_db_session.add(stream)
        await async_db_session.flush()
        async_db_session.add(
            FinanceInsight(
                owner_user_id=1,
                insight_type="price_hike",
                severity="warning",
                title="hike",
                dedup_key="k1",
                related_stream_id=stream.id,
            )
        )
        await async_db_session.flush()  # FK resolves

        async_db_session.add(
            FinanceInsight(
                owner_user_id=1,
                insight_type="price_hike",
                severity="warning",
                title="bad",
                dedup_key="k2",
                related_stream_id=999_999,
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceImportProfile:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceImportProfile

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceImportProfile(
                name="Chase CC",
                source_format="csv",
                amount_sign_convention="outflow_negative",
                header_signature=["Transaction Date", "Description", "Amount"],
                column_mapping={"Amount": "amount", "Description": "name"},
                is_system=True,
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceImportProfile))).one()
        assert row.header_signature == [
            "Transaction Date",
            "Description",
            "Amount",
        ]
        assert row.column_mapping == {"Amount": "amount", "Description": "name"}

    @pytest.mark.asyncio
    async def test_format_and_sign_checks(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceImportProfile

        await _seed_currency(async_db_session, "usd")
        async_db_session.add(
            FinanceImportProfile(
                name="Bad",
                source_format="xlsx",  # not allowed
                amount_sign_convention="outflow_negative",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceImportBatch:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceImportBatch

        async_db_session.add(
            FinanceImportBatch(
                owner_user_id=1,
                source_type="csv",
                file_name="chase.csv",
                file_sha256="abc123",
                rows_total=42,
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceImportBatch))).one()
        assert row.status == "pending"
        assert row.rows_total == 42

    @pytest.mark.asyncio
    async def test_status_check(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceImportBatch

        async_db_session.add(
            FinanceImportBatch(owner_user_id=1, source_type="csv", status="exploded")
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_file_sha_partial_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceImportBatch

        # Same (owner, file_sha256) blocks an identical re-upload.
        for _ in range(2):
            async_db_session.add(
                FinanceImportBatch(
                    owner_user_id=1,
                    source_type="csv",
                    file_sha256="same_file_hash",
                )
            )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceImportBatchRow:
    @pytest.mark.asyncio
    async def test_round_trip_and_unique(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import (
            FinanceImportBatch,
            FinanceImportBatchRow,
        )

        batch = FinanceImportBatch(owner_user_id=1, source_type="csv")
        async_db_session.add(batch)
        await async_db_session.flush()
        async_db_session.add(
            FinanceImportBatchRow(
                import_batch_id=batch.id,
                owner_user_id=1,
                row_number=1,
                parsed={"amount": -4599},
                parsed_status="parsed",
            )
        )
        await async_db_session.flush()
        # One row per (batch, row_number).
        async_db_session.add(
            FinanceImportBatchRow(
                import_batch_id=batch.id,
                owner_user_id=1,
                row_number=1,
                parsed_status="parsed",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()

    @pytest.mark.asyncio
    async def test_batch_fk_required(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceImportBatchRow

        async_db_session.add(
            FinanceImportBatchRow(
                import_batch_id=999_999,
                owner_user_id=1,
                row_number=1,
                parsed_status="parsed",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceAttachment:
    @pytest.mark.asyncio
    async def test_round_trip_and_partial_unique(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.models import FinanceAttachment

        txn = await _seed_transaction(async_db_session)
        async_db_session.add(
            FinanceAttachment(
                owner_user_id=1,
                transaction_id=txn.id,
                file_name="receipt.pdf",
                storage_key="s3://bucket/receipt.pdf",
                sha256="deadbeef",
            )
        )
        await async_db_session.flush()
        # Same (owner, sha256) dedups identical content.
        async_db_session.add(
            FinanceAttachment(
                owner_user_id=1,
                file_name="receipt-copy.pdf",
                storage_key="s3://bucket/receipt-copy.pdf",
                sha256="deadbeef",
            )
        )
        with pytest.raises(IntegrityError):
            await async_db_session.flush()


class TestFinanceTransactionChangelog:
    @pytest.mark.asyncio
    async def test_round_trip(self, async_db_session: AsyncSession) -> None:
        from app.services.finance.models import FinanceTransactionChangelog

        txn = await _seed_transaction(async_db_session)
        async_db_session.add(
            FinanceTransactionChangelog(
                transaction_id=txn.id,
                owner_user_id=1,
                field="category_id",
                old_value=None,
                new_value="42",
                change_source="user",
            )
        )
        await async_db_session.commit()
        row = (await async_db_session.exec(select(FinanceTransactionChangelog))).one()
        assert row.field == "category_id"
        assert row.change_source == "user"
