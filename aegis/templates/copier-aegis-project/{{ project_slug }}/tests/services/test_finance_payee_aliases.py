"""Tests for a payee name that OUTLIVES the transactions it was given to.

Naming a payee used to be a one-time stamp: ``assign_merchant`` set
``merchant_id`` on the rows in front of you and nothing recorded what the
bank descriptor meant. The next import arrived payee-less and offered the
same groups for naming again - on the real ledger, ShopRite among them,
already named months earlier.

The category axis has had this since the beginning
(``FinanceCategoryAlias``: free text -> canonical category, written on
create, read at import). These cover the merchant axis catching up.

An alias keys on ``transaction_payee_key`` - the same four-token
grouping the user was shown when they named it. Keying on the whole
descriptor was tried first and measured against the real ledger, where
it is close to useless: ShopRite's 407 transactions carry 211 distinct
descriptors (the card tail and date are baked into each) and only 8
prefixes, so half of next month's rows would arrive as text nobody had
ever seen.

The prefix is a heuristic, and these pin down what that costs. 5 of the
ledger's 240 named prefixes mean more than one payee - "NON CHASE ATM
WITHDRAW" covers four - so a key taught a second payee is treated as a
conflict rather than a correction, and stops resolving unattended.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.models import FinanceMerchantAlias
from app.services.finance.service import FinanceService
from app.services.finance.utils import normalize_payee, transaction_payee_key
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_payee_txn as _txn

# The descriptor from the live ledger that raised this: a ShopRite the
# review reported as an unnamed, uncategorized payee.
SHOPRITE = "SHPRTE NTH RD&WNSW GT XXX-XXX-6086 NY"
# Same store, different card and day - the variance the four-token prefix
# exists to absorb.
SHOPRITE_AGAIN = "SHPRTE NTH RD&WNSW GT POUGHKEEPSIE NYXX8683 07/22"


KEY = "SHPRTE NTH RD WNSW"  # what both descriptors above group under


async def _stored(session: AsyncSession) -> list[FinanceMerchantAlias]:
    """Every alias row, in ONE read. A test that asks both questions asks
    them of this list rather than running the select twice - which is
    both a waste and the exact shape the N+1 gate watches for."""
    return list((await session.exec(select(FinanceMerchantAlias))).all())


def _by_key(rows: list[FinanceMerchantAlias]) -> dict[str, int]:
    return {row.normalized_alias: row.merchant_id for row in rows}


def _flagged(rows: list[FinanceMerchantAlias]) -> set[str]:
    return {row.normalized_alias for row in rows if row.is_ambiguous}


async def _aliases(session: AsyncSession) -> dict[str, int]:
    return _by_key(await _stored(session))


async def _ambiguous(session: AsyncSession) -> set[str]:
    return _flagged(await _stored(session))


class TestTheKeyAnAliasIsStoredUnder:
    def test_a_swipes_card_tail_and_date_fall_outside_the_key(self) -> None:
        """Why the whole descriptor cannot be the memory: these two are
        the same store on different days, and share only the prefix."""
        assert transaction_payee_key(None, SHOPRITE, None) == KEY
        assert transaction_payee_key(None, SHOPRITE_AGAIN, None) == KEY

    def test_the_merchant_name_wins_over_the_raw_descriptor(self) -> None:
        assert transaction_payee_key("ShopRite", SHOPRITE, "x") == "SHOPRITE"
        assert transaction_payee_key(None, None, "x") == "X"


class TestNamingRecordsWhatItMeant:
    @pytest.mark.asyncio
    async def test_assigning_a_payee_records_the_descriptor(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)

        await svc.assign_merchant([txn.id], shoprite.id, owner_user_id=1)

        assert await _aliases(async_db_session) == {KEY: shoprite.id}

    @pytest.mark.asyncio
    async def test_every_distinct_descriptor_in_the_batch_is_recorded(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Naming a GROUP is one decision, and it is remembered as one
        key - the same key the group was presented under, which is what
        a later row will arrive matching."""
        account = await _account(svc)
        first = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        second = await _txn(svc, account.id, SHOPRITE_AGAIN, date(2026, 7, 22), -3_305)
        third = await _txn(svc, account.id, SHOPRITE, date(2026, 8, 1), -1_200)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)

        await svc.assign_merchant(
            [first.id, second.id, third.id], shoprite.id, owner_user_id=1
        )

        stored = await _stored(async_db_session)
        assert _by_key(stored) == {KEY: shoprite.id}
        assert _flagged(stored) == set()

    @pytest.mark.asyncio
    async def test_clearing_a_payee_records_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """``merchant_id=None`` is an erasure, and an erasure has no name
        to teach."""
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)

        await svc.assign_merchant([txn.id], None, owner_user_id=1)

        assert await _aliases(async_db_session) == {}

    @pytest.mark.asyncio
    async def test_a_second_payee_for_one_key_keeps_the_newer_and_flags_it(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The newest answer is kept - the user just gave it - but the key
        is no longer trusted unattended, because being taught two payees
        is what a genuinely ambiguous descriptor looks like."""
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        wrong = await svc.create_merchant("Shell", owner_user_id=1)
        right = await svc.create_merchant("ShopRite", owner_user_id=1)

        await svc.assign_merchant([txn.id], wrong.id, owner_user_id=1)
        assert await _ambiguous(async_db_session) == set()

        await svc.assign_merchant([txn.id], right.id, owner_user_id=1)

        stored = await _stored(async_db_session)
        assert _by_key(stored) == {KEY: right.id}
        assert _flagged(stored) == {KEY}

    @pytest.mark.asyncio
    async def test_renaming_to_the_same_payee_is_not_a_conflict(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Re-confirming a payee must not poison its own key."""
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)

        await svc.assign_merchant([txn.id], shoprite.id, owner_user_id=1)
        await svc.assign_merchant([txn.id], shoprite.id, owner_user_id=1)

        assert await _ambiguous(async_db_session) == set()

    @pytest.mark.asyncio
    async def test_a_payee_group_assign_records_its_descriptors_too(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """``assign_payee_group`` resolves ids server-side from the keys
        and hands them to ``assign_merchant``, so it inherits the memory
        rather than needing its own."""
        account = await _account(svc)
        await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        await _txn(svc, account.id, SHOPRITE_AGAIN, date(2026, 7, 22), -3_305)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)

        assert await svc.assign_payee_group([KEY], shoprite.id, owner_user_id=1) == 2

        assert await _aliases(async_db_session) == {KEY: shoprite.id}


class TestResolvingADescriptor:
    @pytest.mark.asyncio
    async def test_a_known_descriptor_resolves_to_its_payee(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)
        await svc.assign_merchant([txn.id], shoprite.id, owner_user_id=1)

        resolved = await svc.resolve_merchant_aliases([SHOPRITE], owner_user_id=1)

        assert resolved == {SHOPRITE: shoprite.id}

    @pytest.mark.asyncio
    async def test_a_later_swipe_of_the_same_store_resolves(
        self, svc: FinanceService
    ) -> None:
        """The case that raised the ticket: a different card and day, and
        the payee still lands."""
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)
        await svc.assign_merchant([txn.id], shoprite.id, owner_user_id=1)

        resolved = await svc.resolve_merchant_aliases([SHOPRITE_AGAIN], owner_user_id=1)

        assert resolved == {SHOPRITE_AGAIN: shoprite.id}

    @pytest.mark.asyncio
    async def test_a_key_taught_two_payees_resolves_to_nothing(
        self, svc: FinanceService
    ) -> None:
        """Better to ask than to file every ATM withdrawal under whoever
        was named last."""
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        first = await svc.create_merchant("Shell", owner_user_id=1)
        second = await svc.create_merchant("ShopRite", owner_user_id=1)
        await svc.assign_merchant([txn.id], first.id, owner_user_id=1)
        await svc.assign_merchant([txn.id], second.id, owner_user_id=1)

        assert await svc.resolve_merchant_aliases([SHOPRITE], owner_user_id=1) == {}

    @pytest.mark.asyncio
    async def test_an_unknown_descriptor_is_absent_rather_than_none(
        self, svc: FinanceService
    ) -> None:
        resolved = await svc.resolve_merchant_aliases(
            ["WHO KNOWS", "", None], owner_user_id=1
        )
        assert resolved == {}

    @pytest.mark.asyncio
    async def test_another_owners_alias_is_not_borrowed(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)
        await svc.assign_merchant([txn.id], shoprite.id, owner_user_id=1)

        assert await svc.resolve_merchant_aliases([SHOPRITE], owner_user_id=2) == {}


def _qif(payee: str) -> bytes:
    return (f"!Type:Bank\nD08/15/2026\nT-52.18\nP{payee}\nLGroceries\n^\n").encode()


class TestTheNextImportAlreadyKnows:
    @pytest.mark.asyncio
    async def test_a_named_descriptor_arrives_with_its_payee(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The whole point of the ticket: name it once, and the row that
        lands next month is already filed."""
        from app.services.finance.adapters.importers import imports
        from app.services.finance.adapters.importers.qif import parse_qif

        account = await _account(svc)
        seen = await _txn(svc, account.id, SHOPRITE, date(2026, 6, 28), -8_412)
        shoprite = await svc.create_merchant("ShopRite", owner_user_id=1)
        await svc.assign_merchant([seen.id], shoprite.id, owner_user_id=1)

        data = _qif(SHOPRITE)
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="next-month.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )

        assert result.rows_inserted == 1
        txns, _total = await svc.list_transactions(owner_user_id=1)
        imported = next(t for t in txns if t.id != seen.id)
        assert imported.merchant_id == shoprite.id

    @pytest.mark.asyncio
    async def test_an_unknown_descriptor_still_arrives_payee_less(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """No guessing. An unrecognized descriptor goes to the naming
        backlog exactly as before."""
        from app.services.finance.adapters.importers import imports
        from app.services.finance.adapters.importers.qif import parse_qif

        account = await _account(svc)
        data = _qif("SOME PLACE NOBODY NAMED")
        await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="next-month.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )

        txns, _total = await svc.list_transactions(owner_user_id=1)
        assert [t.merchant_id for t in txns] == [None]


# --- shapes taken verbatim from the live ledger -----------------------------
#
# The rules above are easy to get right on invented strings. These are the
# descriptors that actually exist, with the payees actually attached to
# them, so a later change to normalize_payee or transaction_payee_key has
# to face the data rather than the examples that suited the design.

# One store, 226 rows, a different card tail and date on every swipe.
SHOPRITE_INSTORE = [
    "SHPRTE NTH RD&WNSW GT XXX-XXX-6086 NY 06/28",
    "SHPRTE NTH RD&WNSW GT POUGHKEEPSIE NYXX8683 07/22",
    "SHPRTE NTH RD&WNSW GT XXX-XXX-4474 NY 08/03",
]
# The same store through Apple Pay - a DIFFERENT key, and correctly so.
SHOPRITE_APPLE_PAY = "AplPay SHOPRITE POUGPOUGHKEEPSI"

# One prefix, four real payees: the ledger's worst case.
ATM_HUDSON_VALLEY = "NON-CHASE ATM WITHDRAW XX4474 07/0125 OLD VI"
ATM_CHASE = "NON-CHASE ATM WITHDRAW XX1593 01/1425 OLD VI"


class TestTheShapesTheLedgerActuallyHas:
    def test_every_in_store_swipe_of_one_shoprite_is_one_key(self) -> None:
        """226 rows on the real ledger, no two descriptors identical. This
        is why the whole descriptor cannot be the memory."""
        keys = {transaction_payee_key(None, d, None) for d in SHOPRITE_INSTORE}
        assert keys == {KEY}
        assert len({normalize_payee(d) for d in SHOPRITE_INSTORE}) == 3

    def test_apple_pay_is_a_separate_key_from_the_same_store(self) -> None:
        """Naming the in-store rows must NOT silently claim the wallet
        rows: the prefix groups what a person confirmed, and nobody
        confirmed these together."""
        assert transaction_payee_key(None, SHOPRITE_APPLE_PAY, None) != KEY

    @pytest.mark.asyncio
    async def test_naming_one_swipe_covers_the_rest_of_that_store(
        self, svc: FinanceService
    ) -> None:
        account = await _account(svc)
        seen = await _txn(
            svc, account.id, SHOPRITE_INSTORE[0], date(2026, 6, 28), -8_412
        )
        shoprite = await svc.create_merchant("Shop Rite", owner_user_id=1)
        await svc.assign_merchant([seen.id], shoprite.id, owner_user_id=1)

        resolved = await svc.resolve_merchant_aliases(
            [*SHOPRITE_INSTORE[1:], SHOPRITE_APPLE_PAY], owner_user_id=1
        )

        assert resolved == {d: shoprite.id for d in SHOPRITE_INSTORE[1:]}
        assert SHOPRITE_APPLE_PAY not in resolved

    @pytest.mark.asyncio
    async def test_the_atm_prefix_stops_guessing_once_it_is_shown_two(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """On the real ledger this one prefix covers Hudson Valley
        Grounded (59 rows), Chase - Non Atm Withdraw (152), Chase (3) and
        Fenix Barbershop (1). Whichever was named last would otherwise
        claim every future withdrawal."""
        account = await _account(svc)
        first = await _txn(
            svc, account.id, ATM_HUDSON_VALLEY, date(2026, 7, 1), -20_000
        )
        second = await _txn(svc, account.id, ATM_CHASE, date(2026, 1, 22), -10_000)
        hudson = await svc.create_merchant("Hudson Valley Grounded", owner_user_id=1)
        chase = await svc.create_merchant("Chase", owner_user_id=1)

        await svc.assign_merchant([first.id], hudson.id, owner_user_id=1)
        await svc.assign_merchant([second.id], chase.id, owner_user_id=1)

        assert await _ambiguous(async_db_session) == {"NON CHASE ATM WITHDRAW"}
        assert (
            await svc.resolve_merchant_aliases(
                [ATM_HUDSON_VALLEY, ATM_CHASE], owner_user_id=1
            )
            == {}
        )

    @pytest.mark.asyncio
    async def test_an_aggregator_that_sometimes_means_the_restaurant(
        self, svc: FinanceService
    ) -> None:
        """ "Doordash" is 23 rows of DoorDash and 1 of Wing Stop; "Uber
        Eats" is 50 and 1. The descriptor is identical, so no key could
        separate them - the honest answer is to stop resolving it."""
        account = await _account(svc)
        a = await _txn(svc, account.id, "Doordash", date(2026, 5, 1), -2_400)
        b = await _txn(svc, account.id, "Doordash", date(2026, 5, 2), -3_100)
        doordash = await svc.create_merchant("DoorDash", owner_user_id=1)
        wingstop = await svc.create_merchant("Wing Stop", owner_user_id=1)

        await svc.assign_merchant([a.id], doordash.id, owner_user_id=1)
        await svc.assign_merchant([b.id], wingstop.id, owner_user_id=1)

        assert await svc.resolve_merchant_aliases(["Doordash"], owner_user_id=1) == {}


class TestTheImportAsksOnce:
    @pytest.mark.asyncio
    async def test_payee_resolution_does_not_grow_with_the_row_count(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Descriptors barely repeat within a file - the card tail and
        date vary per swipe - so the per-descriptor cache that works for
        categories would miss on nearly every row here. Caught for real
        while building this: the first version resolved per row and
        tripped the ingest query-count guard.
        """
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        from app.services.finance.adapters.importers import imports
        from app.services.finance.adapters.importers.base import ParsedTransaction

        selects = {"n": 0}

        def _count(conn, cursor, statement, params, context, executemany) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                selects["n"] += 1

        async def _ingest(label: str, n: int) -> int:
            account = await svc.create_manual_account(
                owner_user_id=1,
                name=f"Acct {label}",
                account_type="checking",
                classification="asset",
            )
            parsed = [
                ParsedTransaction(
                    date=date(2026, 1, 1),
                    amount=-100 - i,
                    source="ofx",
                    external_id=f"{label}-{i}",
                    external_id_source="fitid",
                    # Every descriptor distinct, as real swipes are.
                    name=f"SHPRTE NTH RD&WNSW GT XXX-XXX-{i:04d} NY",
                )
                for i in range(n)
            ]
            selects["n"] = 0
            event.listen(Engine, "before_cursor_execute", _count)
            try:
                await imports.ingest_transactions(
                    async_db_session,
                    owner_user_id=1,
                    source_type="ofx",
                    file_name=f"{label}.ofx",
                    file_bytes=f"{label}-{n}".encode(),
                    parsed=parsed,
                    default_account_id=account.id,
                )
            finally:
                event.remove(Engine, "before_cursor_execute", _count)
            return selects["n"]

        small = await _ingest("small", 5)
        large = await _ingest("large", 50)

        # Ten times the rows, at most one more read. The payee lookup is one
        # query for the whole file, like the dedup preload beside it.
        assert large <= small + 1, f"{small} selects for 5 rows, {large} for 50"


class TestRebuildingTheMemoryFromWhatIsAlreadyNamed:
    """The table ships empty, so the 11,189 payees already named on the
    live ledger would teach it nothing - including the ShopRite that
    raised the ticket. This rebuilds it from the namings that already
    exist.

    Not a one-off. ``finance restore`` loads archives written before this
    table existed, and every alias is DERIVED from
    ``transaction_payee_key``, so a change to that key leaves every
    stored row stale with nothing to notice. It sits beside
    ``recompute-snapshots``, which is the same animal.
    """

    @pytest.mark.asyncio
    async def test_it_learns_one_key_per_named_group(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        shoprite = await svc.create_merchant("Shop Rite", owner_user_id=1)
        for day, descriptor in enumerate(SHOPRITE_INSTORE, start=1):
            txn = await _txn(svc, account.id, descriptor, date(2026, 6, day), -8_412)
            # Named the way the ledger was BEFORE aliases existed: the
            # payee is set, nothing records what the descriptor meant.
            txn.merchant_id = shoprite.id
            async_db_session.add(txn)
        await async_db_session.flush()
        assert await _aliases(async_db_session) == {}

        counts = await svc.recompute_payee_aliases(owner_user_id=1)

        assert await _aliases(async_db_session) == {KEY: shoprite.id}
        assert counts == {"transactions": 3, "keys": 1, "ambiguous": 0}

    @pytest.mark.asyncio
    async def test_a_key_two_payees_share_is_flagged_from_the_history(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The ledger's own ATM prefix: the conflict is already sitting in
        the data, so the rebuild has to see it there rather than waiting
        to be taught twice."""
        account = await _account(svc)
        hudson = await svc.create_merchant("Hudson Valley Grounded", owner_user_id=1)
        chase = await svc.create_merchant("Chase", owner_user_id=1)
        for descriptor, merchant in (
            (ATM_HUDSON_VALLEY, hudson),
            (ATM_CHASE, chase),
        ):
            txn = await _txn(svc, account.id, descriptor, date(2026, 7, 1), -20_000)
            txn.merchant_id = merchant.id
            async_db_session.add(txn)
        await async_db_session.flush()

        counts = await svc.recompute_payee_aliases(owner_user_id=1)

        assert counts["ambiguous"] == 1
        assert await _ambiguous(async_db_session) == {"NON CHASE ATM WITHDRAW"}
        assert await svc.resolve_merchant_aliases([ATM_CHASE], owner_user_id=1) == {}

    @pytest.mark.asyncio
    async def test_running_it_twice_changes_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Idempotent, because it is a recompute and not a one-shot: the
        restore path can reach for it whenever an older archive lands."""
        account = await _account(svc)
        shoprite = await svc.create_merchant("Shop Rite", owner_user_id=1)
        txn = await _txn(svc, account.id, SHOPRITE_INSTORE[0], date(2026, 6, 1), -8_412)
        txn.merchant_id = shoprite.id
        async_db_session.add(txn)
        await async_db_session.flush()

        first = await svc.recompute_payee_aliases(owner_user_id=1)
        before = await _aliases(async_db_session)
        second = await svc.recompute_payee_aliases(owner_user_id=1)

        assert first == second
        assert await _aliases(async_db_session) == before

    @pytest.mark.asyncio
    async def test_payee_less_rows_teach_nothing(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await _txn(svc, account.id, SHOPRITE_INSTORE[0], date(2026, 6, 1), -8_412)

        counts = await svc.recompute_payee_aliases(owner_user_id=1)

        assert counts == {"transactions": 0, "keys": 0, "ambiguous": 0}
        assert await _aliases(async_db_session) == {}

    @pytest.mark.asyncio
    async def test_it_drops_a_key_the_data_no_longer_supports(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A recompute answers to the transactions, not to what it wrote
        last time - otherwise clearing a payee would leave the ledger
        still quietly believing the old answer."""
        account = await _account(svc)
        txn = await _txn(svc, account.id, SHOPRITE_INSTORE[0], date(2026, 6, 1), -8_412)
        shoprite = await svc.create_merchant("Shop Rite", owner_user_id=1)
        await svc.assign_merchant([txn.id], shoprite.id, owner_user_id=1)
        assert await _aliases(async_db_session) == {KEY: shoprite.id}

        await svc.assign_merchant([txn.id], None, owner_user_id=1)
        await svc.recompute_payee_aliases(owner_user_id=1)

        assert await _aliases(async_db_session) == {}
