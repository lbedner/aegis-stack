"""Tests for user-declared recurring streams ("Make recurring").

Detection guesses and is allowed to decline; this is the override, so the
cases that matter are the ones detection refuses - two occurrences, or a
cadence matching no canonical gap - plus the reconciliation that has to
happen alongside, because the same bill routinely already exists once or
twice under a drifted descriptor.
"""

from datetime import date

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.domains.detection import (
    declare_recurring,
    detect_recurring,
    plan_recurring,
)
from app.services.finance.models import FinanceRecurringStream, FinanceTransaction
from app.services.finance.service import FinanceService
from app.services.finance.utils import utcnow
from tests.services._finance_factories import live_streams as _live_streams
from tests.services._finance_factories import seed_account as _account
from tests.services._finance_factories import seed_payee_txn as _txn
from tests.services._finance_factories import seed_stream, seed_txn


class TestDeclareRecurring:
    @pytest.mark.asyncio
    async def test_two_occurrences_detection_would_refuse(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """MIN_OCCURRENCES is 3. The user saying "this is my rent" outranks
        a threshold that exists only to keep a guess honest."""
        account = await _account(svc)
        a = await _txn(svc, account.id, "ACME RENT", date(2026, 6, 1), -180_000)
        b = await _txn(svc, account.id, "ACME RENT", date(2026, 7, 1), -180_000)

        assert (
            await detect_recurring(
                async_db_session, owner_user_id=1, today=date(2026, 7, 1)
            )
        ).detected == 0

        result = await declare_recurring(
            async_db_session, [a.id, b.id], owner_user_id=1
        )

        assert (result.streams, result.transactions) == (1, 2)
        stream = (await _live_streams(async_db_session))[0]
        assert stream.is_user_confirmed is True
        assert stream.frequency == "monthly"
        assert stream.next_expected_date == date(2026, 7, 31)  # +30d median

    @pytest.mark.asyncio
    async def test_a_cadence_matching_nothing_is_irregular_not_refused(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Gaps of ~120 days match no canonical cadence, so detection
        declines outright. Declaring keeps the real median instead.

        This used to use ~50 days, which stopped matching nothing once
        ``bimonthly`` joined the ladder: 50 is 10 days off a 60-day
        cadence, well inside the tolerance. 120 sits in the real gap,
        between quarterly's ceiling and semiannual's floor."""
        account = await _account(svc)
        days = [date(2026, 1, 5), date(2026, 5, 5), date(2026, 9, 2)]
        txns = [await _txn(svc, account.id, "ODD BILL", d, -4_200) for d in days]

        assert (
            await detect_recurring(
                async_db_session, owner_user_id=1, today=date(2026, 7, 1)
            )
        ).detected == 0

        result = await declare_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )

        assert result.streams == 1
        stream = (await _live_streams(async_db_session))[0]
        assert stream.frequency == "irregular"
        assert stream.next_expected_date == date(2026, 12, 31)  # +120d median

    @pytest.mark.asyncio
    async def test_a_single_transaction_has_no_cadence_to_measure(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        one = await _txn(svc, account.id, "NEW BILL", date(2026, 7, 1), -2_500)

        result = await declare_recurring(async_db_session, [one.id], owner_user_id=1)

        assert result.streams == 1
        stream = (await _live_streams(async_db_session))[0]
        assert stream.frequency == "unknown"
        assert stream.next_expected_date is None

    @pytest.mark.asyncio
    async def test_selecting_some_sweeps_in_the_rest(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Declaring from 2 of 5 must not leave 3 pointing elsewhere - that
        is what keeps the old stream alive as a duplicate."""
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 6)
        ]

        result = await declare_recurring(
            async_db_session, [txns[0].id, txns[1].id], owner_user_id=1
        )

        assert result.transactions == 5  # not 2
        stream = (await _live_streams(async_db_session))[0]
        linked = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.recurring_stream_id == stream.id
                )
            )
        ).all()
        assert len(linked) == 5

    @pytest.mark.asyncio
    async def test_it_absorbs_the_stream_detection_already_made(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The reconciliation case. Detection found this bill already;
        declaring it must CONFIRM that row, not add a second one."""
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME UTILITIES", date(2026, m, 9), -8_800)
            for m in range(1, 5)
        ]
        assert (
            await detect_recurring(
                async_db_session, owner_user_id=1, today=date(2026, 7, 1)
            )
        ).detected == 1
        detected = (await _live_streams(async_db_session))[0]
        assert detected.is_user_confirmed is False

        result = await declare_recurring(
            async_db_session, [txns[0].id], owner_user_id=1
        )

        assert result.streams == 1
        live = await _live_streams(async_db_session)
        assert len(live) == 1  # absorbed in place, not duplicated
        assert live[0].id == detected.id
        assert live[0].is_user_confirmed is True

    @pytest.mark.asyncio
    async def test_a_drifted_duplicate_is_reconciled_away(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The case this feature exists for. One payee arrived under two
        descriptors, so detection keyed it twice. Naming the payee re-keys
        both groups onto ``merchant:{id}``; declaring then has to leave ONE
        stream standing, with the husks retired.
        """
        account = await _account(svc)
        old = [
            await _txn(svc, account.id, "NETFLIX.COM 866-579", date(2026, m, 7), -1_599)
            for m in range(1, 4)
        ]
        new = [
            await _txn(svc, account.id, "NETFLIX 4013 CA", date(2026, m, 7), -1_599)
            for m in range(4, 7)
        ]
        assert (
            await detect_recurring(
                async_db_session, owner_user_id=1, today=date(2026, 7, 1)
            )
        ).detected == 2
        assert len(await _live_streams(async_db_session)) == 2

        merchant = await svc.create_merchant("Netflix", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in old + new], merchant.id, owner_user_id=1
        )

        result = await declare_recurring(async_db_session, [old[0].id], owner_user_id=1)

        assert result.streams == 1
        assert result.transactions == 6  # both descriptors, one bill
        assert result.reconciled == 2  # the two descriptor-keyed husks
        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].merchant_id == merchant.id
        assert live[0].is_user_confirmed is True

    @pytest.mark.asyncio
    async def test_curation_survives_the_declaration(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A muted bill that un-mutes itself because it was re-keyed is
        worse than one that stays quiet."""
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME NEWS", date(2026, m, 12), -900)
            for m in range(1, 5)
        ]
        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )
        stream = (await _live_streams(async_db_session))[0]
        stream.is_muted = True
        async_db_session.add(stream)
        await async_db_session.flush()

        await declare_recurring(async_db_session, [txns[0].id], owner_user_id=1)

        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].is_muted is True

    @pytest.mark.asyncio
    async def test_separate_accounts_stay_separate_bills(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The stream key includes the account, so the same payee billed on
        two cards is two commitments - merging them would understate what
        is actually leaving each account."""
        first = await _account(svc, "Checking")
        second = await _account(svc, "Savings")
        a = await _txn(svc, first.id, "ACME SAAS", date(2026, 5, 2), -1_000)
        b = await _txn(svc, second.id, "ACME SAAS", date(2026, 5, 2), -1_000)

        result = await declare_recurring(
            async_db_session, [a.id, b.id], owner_user_id=1
        )

        assert result.streams == 2

    @pytest.mark.asyncio
    async def test_empty_selection_is_a_no_op(
        self, async_db_session: AsyncSession
    ) -> None:
        result = await declare_recurring(async_db_session, [], owner_user_id=1)
        assert (result.streams, result.transactions, result.reconciled) == (0, 0, 0)


class TestRecurringPreview:
    """The preview must describe the write exactly, because its whole job
    is to let someone agree to a roll-up they cannot otherwise see."""

    @pytest.mark.asyncio
    async def test_preview_reports_the_full_rollup_not_the_selection(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import plan_recurring

        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 6)
        ]

        plan = await plan_recurring(async_db_session, [txns[0].id], owner_user_id=1)

        assert len(plan) == 1
        group = plan[0]
        assert group.occurrence_count == 5  # what would roll up
        assert group.selected_count == 1  # what was ticked
        assert len(group.members) == 5  # shown in the dialog
        assert group.frequency == "monthly"

    @pytest.mark.asyncio
    async def test_preview_names_the_streams_it_would_fold_in(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        old = [
            await _txn(svc, account.id, "NETFLIX.COM 866-579", date(2026, m, 7), -1_599)
            for m in range(1, 4)
        ]
        new = [
            await _txn(svc, account.id, "NETFLIX 4013 CA", date(2026, m, 7), -1_599)
            for m in range(4, 7)
        ]
        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )
        merchant = await svc.create_merchant("Netflix", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in old + new], merchant.id, owner_user_id=1
        )

        from app.services.finance.domains.detection import plan_recurring

        plan = await plan_recurring(async_db_session, [old[0].id], owner_user_id=1)

        assert len(plan) == 1
        assert plan[0].occurrence_count == 6
        # Both descriptor-keyed streams are named as folding in.
        assert len(plan[0].absorbs) == 2
        assert plan[0].name == "Netflix"  # the payee, not a descriptor

    @pytest.mark.asyncio
    async def test_preview_does_not_write_anything(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import plan_recurring

        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 4)
        ]

        await plan_recurring(async_db_session, [t.id for t in txns], owner_user_id=1)

        assert await _live_streams(async_db_session) == []

    @pytest.mark.asyncio
    async def test_a_typed_name_wins_over_the_proposal(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import plan_recurring

        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "SQ *JOES 0093", date(2026, m, 3), -3_000)
            for m in range(1, 4)
        ]
        plan = await plan_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )
        assert plan[0].name == "SQ *JOES 0093"  # the raw descriptor

        await declare_recurring(
            async_db_session,
            [t.id for t in txns],
            owner_user_id=1,
            names={plan[0].key: "Joe's Coffee"},
        )

        stream = (await _live_streams(async_db_session))[0]
        assert stream.name == "Joe's Coffee"

    @pytest.mark.asyncio
    async def test_an_unnamed_group_keeps_what_the_preview_proposed(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 4)
        ]

        await declare_recurring(
            async_db_session,
            [t.id for t in txns],
            owner_user_id=1,
            names={"some-other-key": "Wrong"},
        )

        stream = (await _live_streams(async_db_session))[0]
        assert stream.name == "ACME GYM"

    @pytest.mark.asyncio
    async def test_plan_keys_are_stable_across_calls(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The UI previews, then sends names back keyed by these - so a key
        that changed between the two calls would silently drop the rename.
        """
        from app.services.finance.domains.detection import plan_recurring

        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 4)
        ]
        ids = [t.id for t in txns]

        first = await plan_recurring(async_db_session, ids, owner_user_id=1)
        second = await plan_recurring(async_db_session, ids, owner_user_id=1)

        assert [g.key for g in first] == [g.key for g in second]


class TestExclusions:
    """Unticking a row has to mean it, permanently.

    ``detect_recurring`` runs nightly at 02:00, after every connection
    sync, after every file import, and on demand from Rescan - four ways
    for a regrouping pass to put an excluded charge straight back. So the
    exclusion is not enforced in the declare path; it is enforced by
    detection refusing to touch a confirmed bill's membership.
    """

    async def _anthropic(self, svc: FinanceService, account_id: int):
        """The real shape: a monthly subscription plus one odd charge from
        the same payee in the same month (usage, not a bill)."""
        subscription = [
            await _txn(
                svc, account_id, "CLAUDE.AI SUBSCRIPTI", date(2026, m, 11), -21_625
            )
            for m in range(1, 8)
        ]
        odd = await _txn(svc, account_id, "ANTHROPIC USAGE", date(2026, 7, 13), -2_209)
        return subscription, odd

    @pytest.mark.asyncio
    async def test_an_excluded_row_stays_out(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        subscription, odd = await self._anthropic(svc, account.id)
        merchant = await svc.create_merchant("Anthropic", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in [*subscription, odd]], merchant.id, owner_user_id=1
        )

        result = await declare_recurring(
            async_db_session,
            [subscription[0].id],
            owner_user_id=1,
            exclude_transaction_ids=[odd.id],
            names={},
        )

        assert result.transactions == 7  # not 8
        await async_db_session.refresh(odd)
        assert odd.recurring_stream_id is None

    @pytest.mark.asyncio
    async def test_the_nightly_pass_does_not_put_it_back(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The whole point. Without pinning, detection regroups every
        Anthropic row under ``merchant:{id}``, finds the confirmed bill,
        and re-adds the charge that was deliberately dropped."""
        account = await _account(svc)
        subscription, odd = await self._anthropic(svc, account.id)
        merchant = await svc.create_merchant("Anthropic", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in [*subscription, odd]], merchant.id, owner_user_id=1
        )
        await declare_recurring(
            async_db_session,
            [subscription[0].id],
            owner_user_id=1,
            exclude_transaction_ids=[odd.id],
            names={"": ""},
        )
        bill = (await _live_streams(async_db_session))[0]

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        await async_db_session.refresh(odd)
        assert odd.recurring_stream_id is None  # still out
        members = (
            await async_db_session.exec(
                select(FinanceTransaction).where(
                    FinanceTransaction.recurring_stream_id == bill.id
                )
            )
        ).all()
        assert len(members) == 7

    @pytest.mark.asyncio
    async def test_detection_leaves_a_confirmed_bills_members_alone(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 5)
        ]
        await declare_recurring(async_db_session, [t.id for t in txns], owner_user_id=1)
        bill = (await _live_streams(async_db_session))[0]

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        assert len(await _live_streams(async_db_session)) == 1
        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.recurring_stream_id == bill.id


class TestDismissalsSurviveDetection:
    """A dismissed proposal is a decision, and detection changes must not
    amnesia it: a key respelling (normalization change, descriptor
    drift) has to re-key the tombstone, not purge it and repropose the
    same bill loud. And a pattern that DIED must not be proposed at all:
    a monthly bill silent for seven months is history, not a bill."""

    @pytest.mark.asyncio
    async def test_a_dismissed_proposals_mute_survives_a_key_rename(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        tombstone = FinanceRecurringStream(
            owner_user_id=1,
            account_id=account.id,
            direction="outflow",
            source="derived",
            is_user_confirmed=False,
            is_muted=True,
            deleted_at=utcnow(),
            # The OLD spelling of the key, before a normalization change.
            normalized_payee="JUSTANSWER LLC XXX XXX 1371 CA XXXX3007",
            name="JUSTANSWER LLC",
            frequency="monthly",
            average_amount=4_600,
        )
        async_db_session.add(tombstone)
        await async_db_session.flush()
        for m in range(3, 7):
            await _txn(
                svc,
                account.id,
                "JUSTANSWER LLC XXX-XXX-1371 CA XXXX3007",
                date(2026, m, 16),
                -4_600,
            )

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        assert await _live_streams(async_db_session) == []  # still silent
        rows = (await async_db_session.exec(select(FinanceRecurringStream))).all()
        assert len(rows) == 1
        adopted = rows[0]
        assert adopted.is_muted is True
        assert adopted.deleted_at is not None
        assert adopted.normalized_payee == "JUSTANSWER LLC CA"  # re-keyed
        assert adopted.occurrence_count == 4  # facts refreshed

    @pytest.mark.asyncio
    async def test_a_monthly_pattern_dead_for_months_is_not_proposed(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        for m in range(1, 6):
            await _txn(svc, account.id, "OLD GYM", date(2026, m, 16), -4_600)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 12, 20)
        )

        assert await _live_streams(async_db_session) == []

    @pytest.mark.asyncio
    async def test_an_annual_bill_survives_its_own_gap(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The silence window scales with cadence: eleven quiet months
        is an annual bill mid-cycle, not a dead one."""
        account = await _account(svc)
        for y in (2024, 2025, 2026):
            await _txn(svc, account.id, "ACME INSURANCE", date(y, 1, 15), -80_000)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 12, 20)
        )

        live = await _live_streams(async_db_session)
        assert [s.frequency for s in live] == ["annually"]


class TestAConfirmedBillIsNotReproposed:
    """A confirmed bill's own history - a dead price era, a descriptor
    with a city tail - regroups as unlinked charges and came back as a
    "new" bill beside the one the user settled ("is it HBO or not?").
    Identity: key tokens nest, same cadence, roughly the bill's price."""

    @pytest.mark.asyncio
    async def test_a_dead_era_of_a_confirmed_bill_is_suppressed(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        await seed_stream(
            svc,
            name="HBO Max",
            expected_amount=1_849,
            next_expected_date=date(2026, 9, 16),
            account_id=account.id,
        )
        for m in range(3, 7):
            await _txn(
                svc,
                account.id,
                "HBO Max NEW YORK NY XXXX3007",
                date(2026, m, 15),
                -1_549,
            )

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        assert [s.name for s in live] == ["HBO Max"]

    @pytest.mark.asyncio
    async def test_the_guard_reads_where_a_standalone_install_writes(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """detect(owner_user_id=None) - the standalone-install path -
        STORES streams under owner 0 (``store_owner``). The guard must
        look for confirmed bills there too: an IS NULL lookup finds
        nothing, and the dead era walks straight past it."""
        account = await _account(svc, owner_user_id=None)
        await seed_stream(
            svc,
            name="HBO Max",
            expected_amount=1_849,
            next_expected_date=date(2026, 9, 16),
            account_id=account.id,
            owner_user_id=0,
        )
        for m in range(3, 7):
            await seed_txn(
                svc,
                account.id,
                -1_549,
                date(2026, m, 15),
                name="HBO Max NEW YORK NY XXXX3007",
                owner_user_id=None,  # type: ignore[arg-type]
            )

        await detect_recurring(async_db_session, owner_user_id=None)

        live = await _live_streams(async_db_session)
        assert [s.name for s in live] == ["HBO Max"]

    @pytest.mark.asyncio
    async def test_a_different_product_of_the_same_payee_still_proposes(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Tokens that OVERLAP but nest neither way are two bills - the
        Anthropic case this machinery exists for."""
        account = await _account(svc)
        await seed_stream(
            svc,
            name="ANTHROPIC SUBS",
            expected_amount=21_625,
            next_expected_date=date(2026, 9, 11),
            account_id=account.id,
        )
        for m in range(3, 7):
            await _txn(svc, account.id, "ANTHROPIC USAGE", date(2026, m, 24), -2_209)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        assert len(live) == 2

    @pytest.mark.asyncio
    async def test_a_nested_key_at_a_foreign_price_still_proposes(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Nested tokens alone are not identity: a premium tier at three
        times the price is a different subscription, not an era."""
        account = await _account(svc)
        await seed_stream(
            svc,
            name="ACME GYM",
            expected_amount=3_000,
            next_expected_date=date(2026, 9, 3),
            account_id=account.id,
        )
        for m in range(3, 7):
            await _txn(svc, account.id, "ACME GYM PRO", date(2026, m, 3), -9_900)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        assert len(live) == 2


class TestDescriptorChurnStillGroups:
    """A processor that embeds the statement date makes every month a
    unique descriptor - one YouTube subscription became "...CA 05/25",
    "...CA 06/25", never reaching MIN_OCCURRENCES, never detected. The
    detection key must survive date fragments and reference numbers."""

    @pytest.mark.asyncio
    async def test_a_date_bearing_descriptor_is_one_stream(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        for m in range(3, 8):
            await _txn(
                svc,
                account.id,
                f"YT PRIMETIME G.CO/HELPPAY# CA {m:02d}/25",
                date(2026, m, 25),
                -999,
            )

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].frequency == "monthly"
        assert live[0].occurrence_count == 5

    @pytest.mark.asyncio
    async def test_a_card_ref_tail_is_one_stream(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The other churn shape: a masked card reference that reformats
        ("XXXX--X4013" then "XXXX4013" then a bare number)."""
        account = await _account(svc)
        tails = ["XXXX--X4013", "XXXX4013", "303450932", "XXXX--X4013", "319079930"]
        for m, tail in enumerate(tails, start=3):
            await _txn(
                svc, account.id, f"DERMSTORE USD DE {tail}", date(2026, m, 7), -3_979
            )

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].occurrence_count == 5


class TestInterleavedAmountsSplit:
    """One payee, two subscriptions, one descriptor: Apple billing $2.99
    iCloud and $12.99 Music interleaves two monthly rhythms. Grouped as
    one, the gaps look like nothing and detection walks away - the
    charges must fall apart into their amount bands and detect as two."""

    @pytest.mark.asyncio
    async def test_two_interleaved_subscriptions_become_two_streams(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        for m in range(2, 8):
            await _txn(svc, account.id, "APPLE.COM/BILL", date(2026, m, 3), -299)
            await _txn(svc, account.id, "APPLE.COM/BILL", date(2026, m, 21), -1_299)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        amounts = sorted(int(s.average_amount) for s in live)
        assert len(live) == 2
        assert amounts == [299, 1_299]
        assert {s.frequency for s in live} == {"monthly"}

    @pytest.mark.asyncio
    async def test_a_live_band_survives_its_dead_sibling(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """One subscription of a pair ends; the mixed group has no whole
        rhythm and only ONE viable band - that band is still a real,
        living bill and must propose alone, not die with its sibling."""
        account = await _account(svc)
        # Interleaved for six months, then the $12.99 sub ends and the
        # $2.99 one runs on alone for a year.
        for m in range(1, 7):
            await _txn(svc, account.id, "APPLE.COM/BILL", date(2025, m, 21), -1_299)
        for m in range(1, 13):
            await _txn(svc, account.id, "APPLE.COM/BILL", date(2025, m, 3), -299)
        for m in range(1, 9):
            await _txn(svc, account.id, "APPLE.COM/BILL", date(2026, m, 3), -299)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 8, 20)
        )

        live = await _live_streams(async_db_session)
        assert [int(s.average_amount) for s in live] == [299]

    @pytest.mark.asyncio
    async def test_a_variable_utility_stays_one_stream(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Splitting is a fallback, never the first move: an electric
        bill swinging seasonally ($80 to $210) has one clean monthly
        rhythm, and amount bands must not carve it up."""
        account = await _account(svc)
        for m, cents in (
            (2, -8_000),
            (3, -12_000),
            (4, -9_500),
            (5, -21_000),
            (6, -8_400),
        ):
            await _txn(svc, account.id, "TOWN ELECTRIC", date(2026, m, 9), cents)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].occurrence_count == 5


class TestMultipleBillsPerPayee:
    """One payee can sell you two things. Anthropic bills a subscription
    and API usage; Amazon bills Prime and AWS. The stream key used to be
    the payee, so the second one could not exist."""

    @pytest.mark.asyncio
    async def test_a_second_bill_lives_beside_the_first(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        subscription = [
            await _txn(svc, account.id, "ANTHROPIC SUBS", date(2026, m, 11), -21_625)
            for m in range(1, 8)
        ]
        usage = [
            await _txn(svc, account.id, "ANTHROPIC USAGE", date(2026, m, 24), -2_209)
            for m in range(1, 8)
        ]
        merchant = await svc.create_merchant("Anthropic", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in [*subscription, *usage]], merchant.id, owner_user_id=1
        )

        await declare_recurring(
            async_db_session,
            [subscription[0].id],
            owner_user_id=1,
            exclude_transaction_ids=[t.id for t in usage],
            names={},
        )
        first = (await _live_streams(async_db_session))[0]
        first.name = "Claude Code"
        async_db_session.add(first)
        await async_db_session.flush()

        # Now declare the excluded half as its own bill.
        await declare_recurring(
            async_db_session,
            [usage[0].id],
            owner_user_id=1,
            exclude_transaction_ids=[t.id for t in subscription],
            names={},
        )

        live = sorted(await _live_streams(async_db_session), key=lambda s: s.id)
        assert len(live) == 2
        # Both default to the PAYEE name, which is why renaming matters:
        # "Anthropic" twice would be two bills you cannot tell apart.
        assert {s.name for s in live} == {"Claude Code", "Anthropic"}
        # Same payee on both, distinct keys so the unique index allows it.
        assert all(s.merchant_id == merchant.id for s in live)
        assert len({s.normalized_payee for s in live}) == 2

    @pytest.mark.asyncio
    async def test_the_preview_says_it_will_be_a_separate_bill(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import plan_recurring

        account = await _account(svc)
        subscription = [
            await _txn(svc, account.id, "ANTHROPIC SUBS", date(2026, m, 11), -21_625)
            for m in range(1, 8)
        ]
        usage = [
            await _txn(svc, account.id, "ANTHROPIC USAGE", date(2026, m, 24), -2_209)
            for m in range(1, 8)
        ]
        merchant = await svc.create_merchant("Anthropic", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in [*subscription, *usage]], merchant.id, owner_user_id=1
        )
        first_plan = await plan_recurring(
            async_db_session,
            [subscription[0].id],
            owner_user_id=1,
            exclude_transaction_ids=[t.id for t in usage],
        )
        await declare_recurring(
            async_db_session,
            [subscription[0].id],
            owner_user_id=1,
            exclude_transaction_ids=[t.id for t in usage],
            names={first_plan[0].key: "Claude Code"},
        )

        plan = await plan_recurring(
            async_db_session,
            [usage[0].id],
            owner_user_id=1,
            exclude_transaction_ids=[t.id for t in subscription],
        )

        assert len(plan) == 1
        assert plan[0].creates_new_bill is True
        assert plan[0].existing_bill_name == "Claude Code"

    @pytest.mark.asyncio
    async def test_redeclaring_the_same_bill_still_absorbs(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The fork must be reserved for genuinely different rows - running
        the same declaration twice has to update one bill, not make two."""
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 5)
        ]
        ids = [t.id for t in txns]

        await declare_recurring(async_db_session, ids, owner_user_id=1)
        await declare_recurring(async_db_session, ids, owner_user_id=1)

        assert len(await _live_streams(async_db_session)) == 1


class TestDetectionLeavesRealBillsAlone:
    """Re-scan is a proposal engine for the DETECTED queue only.

    Anything that reached Bills or Income - confirmed by hand, typed in,
    or shown there because the detector called it a subscription - is off
    limits, along with every transaction inside it. The button exists to
    pick up new payees; it must not be able to rename, re-key, merge,
    re-amount or prune a bill somebody curated.

    The cost is real and deliberate: a curated bill no longer absorbs
    next month's charge, and naming a payee no longer renames it. Growing
    or renaming a bill is now an explicit act.
    """

    @pytest.mark.asyncio
    async def test_a_confirmed_bill_is_not_renamed(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME SUBSCRIPTION", date(2026, m, 4), -1_200)
            for m in range(1, 5)
        ]
        await declare_recurring(async_db_session, [t.id for t in txns], owner_user_id=1)
        merchant = await svc.create_merchant("Acme", owner_user_id=1)
        await svc.assign_merchant([t.id for t in txns], merchant.id, owner_user_id=1)

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].name == "ACME SUBSCRIPTION"  # untouched, not "Acme"
        assert live[0].is_user_confirmed is True

    @pytest.mark.asyncio
    async def test_an_excluded_row_stays_excluded(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """No bookkeeping needed for this any more: the bill is skipped
        wholesale, so there is no pass that could re-absorb the row."""
        account = await _account(svc)
        subscription = [
            await _txn(svc, account.id, "ANTHROPIC SUBS", date(2026, m, 11), -21_625)
            for m in range(1, 8)
        ]
        odd = await _txn(svc, account.id, "ANTHROPIC USAGE", date(2026, 7, 13), -2_209)
        await declare_recurring(
            async_db_session,
            [t.id for t in subscription],
            owner_user_id=1,
            exclude_transaction_ids=[odd.id],
        )

        await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        await async_db_session.refresh(odd)
        assert odd.recurring_stream_id is None

    @pytest.mark.asyncio
    async def test_a_detected_stream_is_still_fair_game(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The other half - nothing above should stop detection doing its
        job on rows nobody has curated."""
        account = await _account(svc)
        for month in range(1, 5):
            await _txn(svc, account.id, "SOME SHOP 123", date(2026, month, 9), -2_500)

        result = await detect_recurring(
            async_db_session, owner_user_id=1, today=date(2026, 7, 1)
        )

        assert result.detected == 1


class TestDeclaredAmount:
    """The amount the USER knows, not the median of whatever the sweep
    rounded up.

    Real case: one $5,000 payroll deposit was picked, the sweep pulled in
    all 32 transactions sharing that bank descriptor ($500 to $16,320),
    and the proposed amount came out $4,420 "varies". The user knew the
    figure; the detector could only average strangers.
    """

    async def _spread(self, svc: FinanceService, account_id: int):
        """One descriptor, wildly different amounts - the shape that makes
        a median meaningless."""
        # Median lands nowhere near the $5,000 pick, which is the point.
        amounts = [50_000, 60_000, 500_000, 70_000, 1_632_000]
        return [
            await _txn(
                svc, account_id, "PURE PROACTIVE H PAYROLL", date(2026, m, 15), a
            )
            for m, a in enumerate(amounts, start=1)
        ]

    @pytest.mark.asyncio
    async def test_the_plan_reports_what_you_actually_picked(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.domains.detection import plan_recurring

        account = await _account(svc)
        txns = await self._spread(svc, account.id)
        picked = txns[2]  # the $5,000 one

        plan = await plan_recurring(async_db_session, [picked.id], owner_user_id=1)

        assert plan[0].occurrence_count == 5  # the whole sweep...
        assert plan[0].selected_amount == 500_000  # ...but this is YOUR number
        assert plan[0].average_amount != 500_000  # the median disagrees

    @pytest.mark.asyncio
    async def test_a_stated_amount_pins_the_bill_fixed(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Same rule update_recurring already follows: stating the amount
        beats the detector's average, so the bill stops reading "varies"."""
        from app.services.finance.domains.detection import plan_recurring

        account = await _account(svc)
        txns = await self._spread(svc, account.id)
        plan = await plan_recurring(async_db_session, [txns[2].id], owner_user_id=1)

        await declare_recurring(
            async_db_session,
            [txns[2].id],
            owner_user_id=1,
            amounts={plan[0].key: 500_000},
        )

        stream = (await _live_streams(async_db_session))[0]
        assert stream.expected_amount == 500_000
        assert stream.amount_is_variable is False

    @pytest.mark.asyncio
    async def test_without_a_stated_amount_nothing_is_pinned(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        txns = await self._spread(svc, account.id)

        await declare_recurring(async_db_session, [txns[2].id], owner_user_id=1)

        stream = (await _live_streams(async_db_session))[0]
        assert stream.expected_amount is None


class TestDeclaringACadence:
    """The user states the cadence, because measuring it cannot always work.

    Detection now knows eight canonical gaps, semiannual included, so the
    case that first forced this - an insurance premium every February and
    August - is found on its own. Plenty is still unmeasurable: a bill on
    a 120-day cycle matches nothing, and an unmatched cadence is stored as
    "irregular", which the forecast cannot STEP. So the bill is correctly
    recognised as recurring and still never appears in the balance line.

    Stating the cadence is what puts it there.
    """

    async def _irregular(self, svc, db):
        """A real rhythm on a cycle no canonical band covers."""
        account = await _account(svc)
        rows = [
            await _txn(svc, account.id, "Odd Bill", day, -200_000)
            for day in (
                date(2025, 1, 5),
                date(2025, 5, 5),
                date(2025, 9, 2),
                date(2025, 12, 31),
            )
        ]
        return account, [r.id for r in rows]

    @pytest.mark.asyncio
    async def test_the_measured_cadence_is_irregular(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The premise: 120 days matches no band, so this is what the
        override exists for."""
        _account_row, ids = await self._irregular(svc, async_db_session)

        await declare_recurring(async_db_session, ids, owner_user_id=1)

        streams = await _live_streams(async_db_session)
        assert streams[0].frequency == "irregular"

    @pytest.mark.asyncio
    async def test_a_semiannual_rhythm_no_longer_needs_the_override(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Geico, the bill that forced this feature, is now measured
        correctly on its own - so the override is a fallback rather than
        the only route into the forecast."""
        account = await _account(svc)
        rows = [
            await _txn(svc, account.id, "Geico", day, -200_000)
            for day in (
                date(2024, 2, 25),
                date(2024, 8, 25),
                date(2025, 2, 25),
                date(2025, 8, 25),
            )
        ]

        await declare_recurring(async_db_session, [r.id for r in rows], owner_user_id=1)

        streams = await _live_streams(async_db_session)
        assert streams[0].frequency == "semi_annually"

    @pytest.mark.asyncio
    async def test_a_stated_cadence_wins_over_the_measured_one(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        _account_row, ids = await self._irregular(svc, async_db_session)

        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)
        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            frequencies={plan[0].key: "quarterly"},
        )

        streams = await _live_streams(async_db_session)
        assert streams[0].frequency == "quarterly"

    @pytest.mark.asyncio
    async def test_the_next_date_follows_the_stated_cadence(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Stating the cadence and leaving the next date where the median
        put it would contradict the instruction on the very next line."""
        _account_row, ids = await self._irregular(svc, async_db_session)

        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)
        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            frequencies={plan[0].key: "quarterly"},
        )

        streams = await _live_streams(async_db_session)
        # Last occurrence 2025-12-31, stepped a quarter, not a 120d median.
        assert streams[0].next_expected_date == date(2026, 3, 31)

    @pytest.mark.asyncio
    async def test_a_stated_cadence_reaches_the_forecast(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """The whole point. An irregular bill cannot be stepped, so it
        never lands in the projection; a stated one does."""
        _account_row, ids = await self._irregular(svc, async_db_session)
        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)
        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            frequencies={plan[0].key: "quarterly"},
            amounts={plan[0].key: 200_000},
        )

        result = await svc.project_balances(
            owner_user_id=1, days=200, today=date(2026, 1, 1)
        )

        assert any(p.name == "Odd Bill" for p in result.points)

    @pytest.mark.asyncio
    async def test_a_cadence_the_forecast_cannot_step_is_refused(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Accepting a label nothing can step would put the bill right
        back where it started, only now looking deliberate."""
        _account_row, ids = await self._irregular(svc, async_db_session)
        plan = await plan_recurring(async_db_session, ids, owner_user_id=1)

        await declare_recurring(
            async_db_session,
            ids,
            owner_user_id=1,
            frequencies={plan[0].key: "whenever"},
        )

        streams = await _live_streams(async_db_session)
        assert streams[0].frequency == "irregular"

    @pytest.mark.asyncio
    async def test_no_override_still_measures(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(svc)
        rows = [
            await _txn(svc, account.id, "Netflix", date(2026, m, 6), -1_599)
            for m in (4, 5, 6)
        ]

        await declare_recurring(async_db_session, [r.id for r in rows], owner_user_id=1)

        streams = await _live_streams(async_db_session)
        assert streams[0].frequency == "monthly"


class TestTheMenuMatchesTheEngine:
    """Every cadence the user can pick has to be one the forecast can
    step. Offering one it cannot is how a bill becomes invisible while
    looking correctly configured, which is the failure this whole feature
    exists to fix - so it must not be reintroduced by the menu itself.
    """

    def test_every_offered_cadence_can_be_stepped(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            _FREQUENCY_LABELS,
        )
        from app.services.finance.utils import FREQUENCY_STEPS

        assert set(_FREQUENCY_LABELS) <= set(FREQUENCY_STEPS)

    def test_every_steppable_cadence_can_be_picked(self) -> None:
        """The other direction, and the actual bug: the forecast could
        step semiannual and bimonthly long before anything let a user say
        so."""
        from app.components.frontend.dashboard.modals.finance_modal import (
            _FREQUENCY_LABELS,
        )
        from app.services.finance.utils import FREQUENCY_STEPS

        assert set(FREQUENCY_STEPS) <= set(_FREQUENCY_LABELS)
