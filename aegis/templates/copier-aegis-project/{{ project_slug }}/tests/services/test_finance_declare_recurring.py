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

from app.services.finance.categorize import declare_recurring, detect_recurring
from app.services.finance.finance_service import FinanceService
from app.services.finance.models import FinanceRecurringStream, FinanceTransaction


async def _account(svc: FinanceService, name: str = "Checking"):
    return await svc.create_manual_account(
        name=name,
        account_type="checking",
        classification="asset",
        owner_user_id=1,
    )


async def _txn(svc: FinanceService, account_id: int, name: str, day: date, cents: int):
    return await svc.create_transaction(
        account_id=account_id,
        amount=cents,
        txn_date=day,
        owner_user_id=1,
        name=name,
    )


async def _live_streams(db: AsyncSession) -> list[FinanceRecurringStream]:
    return list(
        (
            await db.exec(
                select(FinanceRecurringStream).where(
                    FinanceRecurringStream.deleted_at.is_(None)
                )
            )
        ).all()
    )


class TestDeclareRecurring:
    @pytest.mark.asyncio
    async def test_two_occurrences_detection_would_refuse(
        self, async_db_session: AsyncSession
    ) -> None:
        """MIN_OCCURRENCES is 3. The user saying "this is my rent" outranks
        a threshold that exists only to keep a guess honest."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        a = await _txn(svc, account.id, "ACME RENT", date(2026, 6, 1), -180_000)
        b = await _txn(svc, account.id, "ACME RENT", date(2026, 7, 1), -180_000)

        assert (await detect_recurring(async_db_session, owner_user_id=1)).detected == 0

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
        self, async_db_session: AsyncSession
    ) -> None:
        """Gaps of ~50 days match no canonical cadence, so detection
        declines outright. Declaring keeps the real median instead."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        days = [date(2026, 1, 5), date(2026, 2, 24), date(2026, 4, 15)]
        txns = [await _txn(svc, account.id, "ODD BILL", d, -4_200) for d in days]

        assert (await detect_recurring(async_db_session, owner_user_id=1)).detected == 0

        result = await declare_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )

        assert result.streams == 1
        stream = (await _live_streams(async_db_session))[0]
        assert stream.frequency == "irregular"
        assert stream.next_expected_date == date(2026, 6, 4)  # +50d median

    @pytest.mark.asyncio
    async def test_a_single_transaction_has_no_cadence_to_measure(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        one = await _txn(svc, account.id, "NEW BILL", date(2026, 7, 1), -2_500)

        result = await declare_recurring(async_db_session, [one.id], owner_user_id=1)

        assert result.streams == 1
        stream = (await _live_streams(async_db_session))[0]
        assert stream.frequency == "unknown"
        assert stream.next_expected_date is None

    @pytest.mark.asyncio
    async def test_selecting_some_sweeps_in_the_rest(
        self, async_db_session: AsyncSession
    ) -> None:
        """Declaring from 2 of 5 must not leave 3 pointing elsewhere - that
        is what keeps the old stream alive as a duplicate."""
        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        """The reconciliation case. Detection found this bill already;
        declaring it must CONFIRM that row, not add a second one."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME UTILITIES", date(2026, m, 9), -8_800)
            for m in range(1, 5)
        ]
        assert (await detect_recurring(async_db_session, owner_user_id=1)).detected == 1
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
        self, async_db_session: AsyncSession
    ) -> None:
        """The case this feature exists for. One payee arrived under two
        descriptors, so detection keyed it twice. Naming the payee re-keys
        both groups onto ``merchant:{id}``; declaring then has to leave ONE
        stream standing, with the husks retired.
        """
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        old = [
            await _txn(svc, account.id, "NETFLIX.COM 866-579", date(2026, m, 7), -1_599)
            for m in range(1, 4)
        ]
        new = [
            await _txn(svc, account.id, "NETFLIX 4013 CA", date(2026, m, 7), -1_599)
            for m in range(4, 7)
        ]
        assert (await detect_recurring(async_db_session, owner_user_id=1)).detected == 2
        assert len(await _live_streams(async_db_session)) == 2

        merchant = await svc.create_merchant("Netflix", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in old + new], merchant.id, owner_user_id=1
        )

        result = await declare_recurring(
            async_db_session, [old[0].id], owner_user_id=1
        )

        assert result.streams == 1
        assert result.transactions == 6  # both descriptors, one bill
        assert result.reconciled == 2  # the two descriptor-keyed husks
        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].merchant_id == merchant.id
        assert live[0].is_user_confirmed is True

    @pytest.mark.asyncio
    async def test_curation_survives_the_declaration(
        self, async_db_session: AsyncSession
    ) -> None:
        """A muted bill that un-mutes itself because it was re-keyed is
        worse than one that stays quiet."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME NEWS", date(2026, m, 12), -900)
            for m in range(1, 5)
        ]
        await detect_recurring(async_db_session, owner_user_id=1)
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
        self, async_db_session: AsyncSession
    ) -> None:
        """The stream key includes the account, so the same payee billed on
        two cards is two commitments - merging them would understate what
        is actually leaving each account."""
        svc = FinanceService(async_db_session)
        first = await _account(svc, "Checking")
        second = await _account(svc, "Savings")
        a = await _txn(svc, first.id, "ACME SAAS", date(2026, 5, 2), -1_000)
        b = await _txn(svc, second.id, "ACME SAAS", date(2026, 5, 2), -1_000)

        result = await declare_recurring(async_db_session, [a.id, b.id], owner_user_id=1)

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
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        old = [
            await _txn(svc, account.id, "NETFLIX.COM 866-579", date(2026, m, 7), -1_599)
            for m in range(1, 4)
        ]
        new = [
            await _txn(svc, account.id, "NETFLIX 4013 CA", date(2026, m, 7), -1_599)
            for m in range(4, 7)
        ]
        await detect_recurring(async_db_session, owner_user_id=1)
        merchant = await svc.create_merchant("Netflix", owner_user_id=1)
        await svc.assign_merchant(
            [t.id for t in old + new], merchant.id, owner_user_id=1
        )

        from app.services.finance.categorize import plan_recurring

        plan = await plan_recurring(async_db_session, [old[0].id], owner_user_id=1)

        assert len(plan) == 1
        assert plan[0].occurrence_count == 6
        # Both descriptor-keyed streams are named as folding in.
        assert len(plan[0].absorbs) == 2
        assert plan[0].name == "Netflix"  # the payee, not a descriptor

    @pytest.mark.asyncio
    async def test_preview_does_not_write_anything(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 4)
        ]

        await plan_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )

        assert await _live_streams(async_db_session) == []

    @pytest.mark.asyncio
    async def test_a_typed_name_wins_over_the_proposal(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        """The UI previews, then sends names back keyed by these - so a key
        that changed between the two calls would silently drop the rename.
        """
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
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
            await _txn(svc, account_id, "CLAUDE.AI SUBSCRIPTI", date(2026, m, 11), -21_625)
            for m in range(1, 8)
        ]
        odd = await _txn(svc, account_id, "ANTHROPIC USAGE", date(2026, 7, 13), -2_209)
        return subscription, odd

    @pytest.mark.asyncio
    async def test_an_excluded_row_stays_out(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        """The whole point. Without pinning, detection regroups every
        Anthropic row under ``merchant:{id}``, finds the confirmed bill,
        and re-adds the charge that was deliberately dropped."""
        svc = FinanceService(async_db_session)
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

        await detect_recurring(async_db_session, owner_user_id=1)

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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 5)
        ]
        await declare_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )
        bill = (await _live_streams(async_db_session))[0]

        await detect_recurring(async_db_session, owner_user_id=1)

        assert len(await _live_streams(async_db_session)) == 1
        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.recurring_stream_id == bill.id


class TestMultipleBillsPerPayee:
    """One payee can sell you two things. Anthropic bills a subscription
    and API usage; Amazon bills Prime and AWS. The stream key used to be
    the payee, so the second one could not exist."""

    @pytest.mark.asyncio
    async def test_a_second_bill_lives_beside_the_first(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        """The fork must be reserved for genuinely different rows - running
        the same declaration twice has to update one bill, not make two."""
        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME SUBSCRIPTION", date(2026, m, 4), -1_200)
            for m in range(1, 5)
        ]
        await declare_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )
        merchant = await svc.create_merchant("Acme", owner_user_id=1)
        await svc.assign_merchant([t.id for t in txns], merchant.id, owner_user_id=1)

        await detect_recurring(async_db_session, owner_user_id=1)

        live = await _live_streams(async_db_session)
        assert len(live) == 1
        assert live[0].name == "ACME SUBSCRIPTION"  # untouched, not "Acme"
        assert live[0].is_user_confirmed is True

    @pytest.mark.asyncio
    async def test_a_confirmed_bills_members_never_move(
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = [
            await _txn(svc, account.id, "ACME GYM", date(2026, m, 3), -3_000)
            for m in range(1, 5)
        ]
        await declare_recurring(
            async_db_session, [t.id for t in txns], owner_user_id=1
        )
        bill = (await _live_streams(async_db_session))[0]

        await detect_recurring(async_db_session, owner_user_id=1)

        assert len(await _live_streams(async_db_session)) == 1
        for txn in txns:
            await async_db_session.refresh(txn)
            assert txn.recurring_stream_id == bill.id

    @pytest.mark.asyncio
    async def test_an_excluded_row_stays_excluded(
        self, async_db_session: AsyncSession
    ) -> None:
        """No bookkeeping needed for this any more: the bill is skipped
        wholesale, so there is no pass that could re-absorb the row."""
        svc = FinanceService(async_db_session)
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

        await detect_recurring(async_db_session, owner_user_id=1)

        await async_db_session.refresh(odd)
        assert odd.recurring_stream_id is None

    @pytest.mark.asyncio
    async def test_a_detected_stream_is_still_fair_game(
        self, async_db_session: AsyncSession
    ) -> None:
        """The other half - nothing above should stop detection doing its
        job on rows nobody has curated."""
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        for month in range(1, 5):
            await _txn(svc, account.id, "SOME SHOP 123", date(2026, month, 9), -2_500)

        result = await detect_recurring(async_db_session, owner_user_id=1)

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
            await _txn(svc, account_id, "PURE PROACTIVE H PAYROLL", date(2026, m, 15), a)
            for m, a in enumerate(amounts, start=1)
        ]

    @pytest.mark.asyncio
    async def test_the_plan_reports_what_you_actually_picked(
        self, async_db_session: AsyncSession
    ) -> None:
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = await self._spread(svc, account.id)
        picked = txns[2]  # the $5,000 one

        plan = await plan_recurring(async_db_session, [picked.id], owner_user_id=1)

        assert plan[0].occurrence_count == 5  # the whole sweep...
        assert plan[0].selected_amount == 500_000  # ...but this is YOUR number
        assert plan[0].average_amount != 500_000  # the median disagrees

    @pytest.mark.asyncio
    async def test_a_stated_amount_pins_the_bill_fixed(
        self, async_db_session: AsyncSession
    ) -> None:
        """Same rule update_recurring already follows: stating the amount
        beats the detector's average, so the bill stops reading "varies"."""
        from app.services.finance.categorize import plan_recurring

        svc = FinanceService(async_db_session)
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
        self, async_db_session: AsyncSession
    ) -> None:
        svc = FinanceService(async_db_session)
        account = await _account(svc)
        txns = await self._spread(svc, account.id)

        await declare_recurring(async_db_session, [txns[2].id], owner_user_id=1)

        stream = (await _live_streams(async_db_session))[0]
        assert stream.expected_amount is None
