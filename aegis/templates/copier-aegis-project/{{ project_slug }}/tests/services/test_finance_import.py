"""Tests for the OFX/QFX importer + import pipeline (FIN-14).

Plain ``.py`` (finance-only stacks). Uses the hand-crafted
``finance/fixtures/sample_chase.qfx`` (6 transactions covering debit, credit,
a check, a same-day/same-amount pair with distinct FITIDs, and a messy payee).
"""

from pathlib import Path

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.adapters.importers import imports
from app.services.finance.adapters.importers.base import (
    ParsedTransaction,
    compute_import_hash,
)
from app.services.finance.adapters.importers.ofx import parse_ofx
from app.services.finance.adapters.importers.qif import parse_qif
from app.services.finance.models import FinanceAccount
from app.services.finance.service import FinanceService
from app.services.finance.utils import (
    normalize_payee,
)

_FIXTURES = Path(__file__).parent / "finance" / "fixtures"


def _qfx() -> bytes:
    return (_FIXTURES / "sample_chase.qfx").read_bytes()


def _qif() -> bytes:
    return (_FIXTURES / "sample_quicken.qif").read_bytes()


async def _account(session: AsyncSession) -> FinanceAccount:
    return await FinanceService(session).create_manual_account(
        owner_user_id=1,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )


class TestNormalizePayee:
    def test_normalizes(self) -> None:
        # NFKD fold: accented and plain spellings collapse to one key.
        assert normalize_payee("  Café   Münchén!! ") == "CAFE MUNCHEN"
        assert normalize_payee("Cafe Munchen") == "CAFE MUNCHEN"
        assert normalize_payee("WHOLE FOODS MKT #123") == "WHOLE FOODS MKT 123"
        assert normalize_payee(None) == ""


class TestParseOfx:
    def test_parses_six_with_correct_signs_and_cents(self) -> None:
        parsed = parse_ofx(_qfx(), source="qfx")
        assert len(parsed) == 6
        by_id = {p.external_id: p for p in parsed}
        assert by_id["F001"].amount == -14230  # debit -> negative
        assert by_id["F002"].amount == 320000  # credit -> positive
        assert by_id["F003"].amount == -8999
        assert by_id["F003"].check_number == "1042"
        assert by_id["F004"].amount == -650
        assert all(p.external_id_source == "fitid" for p in parsed)
        assert by_id["F001"].account_key == "1234567890"


class TestImportPipeline:
    @pytest.mark.asyncio
    async def test_import_inserts_with_correct_signs(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(async_db_session)
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qfx",
            file_name="sample_chase.qfx",
            file_bytes=_qfx(),
            parsed=parse_ofx(_qfx(), source="qfx"),
            default_account_id=account.id,
        )
        assert result.rows_total == 6
        assert result.rows_inserted == 6
        assert result.rows_duplicate == 0

        txns, total = await svc.list_transactions(
            owner_user_id=1, account_id=account.id
        )
        assert total == 6
        amounts = {t.external_id: t.amount for t in txns}
        assert amounts["F001"] == -14230
        assert amounts["F002"] == 320000

    @pytest.mark.asyncio
    async def test_same_file_reimport_short_circuits(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(async_db_session)
        data = _qfx()
        first = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qfx",
            file_name="c.qfx",
            file_bytes=data,
            parsed=parse_ofx(data, source="qfx"),
            default_account_id=account.id,
        )
        assert first.rows_inserted == 6

        second = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qfx",
            file_name="c.qfx",
            file_bytes=data,
            parsed=parse_ofx(data, source="qfx"),
            default_account_id=account.id,
        )
        assert second.rows_inserted == 0
        assert second.rows_duplicate == 6
        assert second.batch_id == first.batch_id  # short-circuited to prior

        _, total = await svc.list_transactions(owner_user_id=1, account_id=account.id)
        assert total == 6  # unchanged

    @pytest.mark.asyncio
    async def test_an_empty_field_is_not_an_edit(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A statement whose memo column is blank re-imports as "already
        have", not as 235 rows "changed in place": an empty cell and a
        missing one are the same absence."""
        account = await _account(async_db_session)
        data = _qif()
        await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )
        rows, _total = await svc.list_transactions(owner_user_id=1, account_id=account.id)
        target = rows[0]

        same_money_blank_memo = ParsedTransaction(
            date=target.date_,
            amount=target.amount,
            name=target.name,
            source="qif",
            memo="",
        )
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q2.qif",
            file_bytes=b"different bytes",
            parsed=[same_money_blank_memo],
            default_account_id=account.id,
        )

        assert result.rows_updated == 0
        assert result.rows_inserted == 0

    @pytest.mark.asyncio
    async def test_edited_row_updates_in_place_instead_of_duplicating(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """An edit in the source app (payee/category/memo) must UPDATE the
        existing transaction. The content hash covers those fields, so
        without lane 3 a re-export lands the same money twice."""
        account = await _account(async_db_session)
        data = _qif()
        first = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )
        assert first.rows_inserted > 0

        before, total_before = await svc.list_transactions(
            owner_user_id=1, account_id=account.id
        )
        target = before[0]
        original_amount, original_date = target.amount, target.date_

        # Same money, renamed payee + new category: one edited row.
        edited = ParsedTransaction(
            date=original_date,
            amount=original_amount,
            name="RENAMED BY USER",
            source="qif",
            category_hint="Bills & Utilities:Water",
            memo="edited memo",
        )
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q2.qif",
            file_bytes=b"different bytes",
            parsed=[edited],
            default_account_id=account.id,
        )
        assert result.rows_updated == 1
        assert result.rows_inserted == 0

        after, total_after = await svc.list_transactions(
            owner_user_id=1, account_id=account.id
        )
        assert total_after == total_before  # no second copy of the money
        touched = next(t for t in after if t.id == target.id)
        assert touched.name == "RENAMED BY USER"
        assert touched.memo == "edited memo"
        assert touched.category_id is not None
        # The hash is restamped, so the NEXT import sees a plain duplicate.
        again = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q3.qif",
            file_bytes=b"different bytes again",
            parsed=[
                ParsedTransaction(
                    date=original_date,
                    amount=original_amount,
                    name="RENAMED BY USER",
                    source="qif",
                    category_hint="Bills & Utilities:Water",
                    memo="edited memo",
                )
            ],
            default_account_id=account.id,
        )
        assert again.rows_duplicate == 1
        assert again.rows_updated == 0

    @pytest.mark.asyncio
    async def test_ambiguous_same_day_same_amount_rows_are_not_merged(
        self, async_db_session: AsyncSession
    ) -> None:
        """Two same-day, same-amount charges are indistinguishable once a
        payee is edited, so lane 3 must refuse to guess and insert."""
        from datetime import date as date_cls

        account = await _account(async_db_session)
        twins = [
            ParsedTransaction(
                date=date_cls(2026, 7, 1),
                amount=-4500,
                name=f"Corner Bistro {n}",
                source="qif",
            )
            for n in (1, 2)
        ]
        await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="t.qif",
            file_bytes=b"twins",
            parsed=twins,
            default_account_id=account.id,
        )
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="t2.qif",
            file_bytes=b"twins edited",
            parsed=[
                ParsedTransaction(
                    date=date_cls(2026, 7, 1),
                    amount=-4500,
                    name="Corner Bistro RENAMED",
                    source="qif",
                )
            ],
            default_account_id=account.id,
        )
        assert result.rows_updated == 0  # refuses to guess which twin
        assert result.rows_inserted == 1

    @pytest.mark.asyncio
    async def test_overlapping_file_inserts_only_new_row(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(async_db_session)
        data = _qfx()
        await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qfx",
            file_name="c.qfx",
            file_bytes=data,
            parsed=parse_ofx(data, source="qfx"),
            default_account_id=account.id,
        )
        # Same FITIDs F001-F005, but F006 becomes a brand-new F007 (diff bytes).
        overlapping = data.replace(b"<FITID>F006", b"<FITID>F007")
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qfx",
            file_name="c2.qfx",
            file_bytes=overlapping,
            parsed=parse_ofx(overlapping, source="qfx"),
            default_account_id=account.id,
        )
        assert result.rows_inserted == 1
        assert result.rows_duplicate == 5

        _, total = await svc.list_transactions(owner_user_id=1, account_id=account.id)
        assert total == 7  # 6 original + 1 new

    @pytest.mark.asyncio
    async def test_ingest_query_count_is_flat_in_row_count(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Ingest preloads dedup lanes + memoizes categories, so its SELECT
        count does not grow with the number of rows (guards the old per-row
        find_transaction + resolve_category_alias N+1)."""
        from datetime import date

        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        from app.services.finance.adapters.importers.base import ParsedTransaction

        def _rows(n: int, label: str) -> list[ParsedTransaction]:
            # Distinct external_ids (LANE 1) with a shared category string so
            # the alias cache is exercised across every row.
            return [
                ParsedTransaction(
                    date=date(2026, 1, 1),
                    amount=-100 - i,
                    source="ofx",
                    external_id=f"{label}-{i}",
                    external_id_source="fitid",
                    name=f"Payee {i}",
                    category_hint="Groceries",
                )
                for i in range(n)
            ]

        selects = {"n": 0}

        def _on_exec(conn, cursor, statement, params, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects["n"] += 1

        async def _ingest(label: str, n: int) -> int:
            account = await svc.create_manual_account(
                owner_user_id=1,
                name=f"Acct {label}",
                account_type="checking",
                classification="asset",
            )
            event.listen(Engine, "before_cursor_execute", _on_exec)
            try:
                selects["n"] = 0
                await imports.ingest_transactions(
                    async_db_session,
                    owner_user_id=1,
                    source_type="ofx",
                    file_name=f"{label}.ofx",
                    file_bytes=f"{label}-{n}".encode(),
                    parsed=_rows(n, label),
                    default_account_id=account.id,
                )
                return selects["n"]
            finally:
                event.remove(Engine, "before_cursor_execute", _on_exec)

        small = await _ingest("small", 3)
        large = await _ingest("large", 30)

        # 10x the rows must not mean 10x the SELECTs. Reads are the sha-check,
        # account resolve, dedup preload, and the first category lookup — all
        # independent of row count.
        assert large <= small + 1, f"query count grew with rows: {small} -> {large}"


# ---------------------------------------------------------------------------
# QIF (LANE-2 content hash) — FIN-15
# ---------------------------------------------------------------------------


class TestImportHashRecipe:
    def test_hash_is_pinned(self) -> None:
        """Guards accidental recipe drift — a change silently breaks dedup for
        every existing import, so this value must never change unintentionally."""
        from datetime import date

        assert (
            compute_import_hash(
                account_id=42,
                txn_date=date(2026, 7, 1),
                amount_cents=-4599,
                payee="Blue Bottle",
                memo="coffee",
                check_number=None,
                within_day_ordinal=0,
            )
            == "a015a1bde36843f9d7c2cfee0bd4bea839500536cd58196d3153caec29b4f74d"
        )


class TestParseQif:
    def test_parses_eight_with_splits_and_transfer(self) -> None:
        parsed = parse_qif(_qif(), source="qif")
        assert len(parsed) == 8
        assert all(p.external_id is None for p in parsed)  # LANE 2
        by_payee = {p.name: p for p in parsed}
        assert by_payee["Blue Bottle Coffee"].amount == -4599
        assert by_payee["ACME Payroll"].amount == 320000
        assert by_payee["Comcast"].check_number == "1055"
        # split parent: 3 legs summing to the parent
        supermarket = by_payee["Supermarket"]
        assert len(supermarket.splits) == 3
        assert sum(s.amount for s in supermarket.splits) == supermarket.amount
        # transfer marker captured but not paired here
        transfer = by_payee["Transfer to Savings"]
        assert transfer.transfer_hint == "[Savings]"
        assert transfer.category_hint is None

    def test_investment_qif_rejected(self) -> None:
        with pytest.raises(ValueError, match="investment QIF"):
            parse_qif(b"!Type:Invst\nD07/01/2026\n^\n", source="qif")

    def test_two_digit_year_pivots_correctly(self) -> None:
        """2-digit QIF years: apostrophe => 2000s; else pivot on 69 so legacy
        1900s dates don't jump to the 2000s (Copilot review)."""
        from datetime import date

        from app.services.finance.adapters.importers.qif import _parse_qif_date

        assert _parse_qif_date("12/31/99") == date(1999, 12, 31)  # legacy 1900s
        assert _parse_qif_date("1/5'20") == date(2020, 1, 5)  # apostrophe => 2000s
        assert _parse_qif_date("7/8/26") == date(2026, 7, 8)  # <=68 => 2000s
        assert _parse_qif_date("01/02/2026") == date(2026, 1, 2)  # 4-digit as-is


async def _seed_dining_alias(session: AsyncSession) -> int:
    from app.services.finance.models import FinanceCategory, FinanceCategoryAlias

    category = FinanceCategory(slug="dining", name="Dining", classification="expense")
    session.add(category)
    await session.flush()
    session.add(
        FinanceCategoryAlias(
            category_id=category.id, alias_text="Dining", normalized_alias="DINING"
        )
    )
    await session.flush()
    return category.id


class TestQifImport:
    @pytest.mark.asyncio
    async def test_import_splits_ordinals_categories(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select

        from app.services.finance.models import FinanceTransactionSplit

        account = await _account(async_db_session)
        category_id = await _seed_dining_alias(async_db_session)
        data = _qif()
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )
        assert result.rows_inserted == 8

        txns, total = await svc.list_transactions(
            owner_user_id=1, account_id=account.id
        )
        assert total == 8

        # identical same-day rows both import via distinct ordinals
        parking = [t for t in txns if t.name == "Parking Garage"]
        assert len(parking) == 2
        assert {t.within_day_ordinal for t in parking} == {0, 1}

        # split parent flagged + 3 legs summing to parent cents
        supermarket = next(t for t in txns if t.name == "Supermarket")
        assert supermarket.is_split is True
        splits = (
            await async_db_session.exec(
                select(FinanceTransactionSplit).where(
                    FinanceTransactionSplit.parent_transaction_id == supermarket.id
                )
            )
        ).all()
        assert len(splits) == 3
        assert sum(s.amount for s in splits) == -10000

        # alias-matched rows got the seeded category; unknown hints now
        # CREATE a category (the user's own curation is not droppable data).
        dining = [t for t in txns if t.name in ("Blue Bottle Coffee", "Gym Membership")]
        assert all(t.category_id == category_id for t in dining)
        comcast = next(t for t in txns if t.name == "Comcast")
        assert comcast.category_id is not None
        assert comcast.category_id != category_id  # its own "Utilities" category

    @pytest.mark.asyncio
    async def test_reimport_same_file_zero_new(
        self, async_db_session: AsyncSession
    ) -> None:
        account = await _account(async_db_session)
        data = _qif()
        await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )
        second = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )
        assert second.rows_inserted == 0

    @pytest.mark.asyncio
    async def test_extended_export_inserts_only_new(
        self, async_db_session: AsyncSession
    ) -> None:
        account = await _account(async_db_session)
        data = _qif()
        await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q.qif",
            file_bytes=data,
            parsed=parse_qif(data, source="qif"),
            default_account_id=account.id,
        )
        # Same 8 rows + 2 new ones, different bytes -> hash dedup, not sha.
        extended = data + (
            b"D07/09/2026\nT-15.00\nPNew Cafe\n^\nD07/10/2026\nT-20.00\nPNew Store\n^\n"
        )
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="qif",
            file_name="q2.qif",
            file_bytes=extended,
            parsed=parse_qif(extended, source="qif"),
            default_account_id=account.id,
        )
        assert result.rows_inserted == 2
        assert result.rows_duplicate == 8


# ---------------------------------------------------------------------------
# CSV (profile-driven) — FIN-16
# ---------------------------------------------------------------------------


def _csv(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _profiles() -> list:
    from app.services.finance.models import FinanceImportProfile
    from app.services.finance.seeds.seed import CSV_IMPORT_PROFILES

    return [FinanceImportProfile(is_system=True, **p) for p in CSV_IMPORT_PROFILES]


async def _seed_csv_profiles(session: AsyncSession) -> None:
    # Profiles reference a currency (FK), so seed currencies first — matching
    # production seed order — so the helper works even when no account has been
    # created yet. get_or_create is idempotent for callers that already have.
    from app.services.finance.seeds.seed import DEFAULT_CURRENCIES

    svc = FinanceService(session)
    for currency in DEFAULT_CURRENCIES:
        await svc.get_or_create_currency(currency["code"])
    for profile in _profiles():
        session.add(profile)
    await session.flush()


class TestPreviewNeedsAnAccount:
    """A single-account layout with no target is not an error to throw
    back: the preview says so, and names the layout, so the client can
    ask which account the statement belongs to before anything else."""

    @pytest.mark.asyncio
    async def test_no_target_previews_as_a_question(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed_csv_profiles(async_db_session)

        plan = await imports.preview_file(
            async_db_session,
            owner_user_id=1,
            file_name="card.csv",
            file_bytes=_csv("sample_chase_cc.csv"),
            account_id=None,
        )

        assert plan.needs_account is True
        assert plan.layout == "Chase Credit Card"
        assert plan.rows_total > 0
        assert plan.rows == []

    @pytest.mark.asyncio
    async def test_a_targeted_preview_names_layout_and_account(
        self, async_db_session: AsyncSession
    ) -> None:
        """The review dialog shows "Chase Credit Card layout into Checking"
        so a statement aimed at the wrong account is caught by eye."""
        from app.components.backend.api.finance.declare import _preview_payload

        await _seed_csv_profiles(async_db_session)
        account = await _account(async_db_session)

        plan = await imports.preview_file(
            async_db_session,
            owner_user_id=1,
            file_name="card.csv",
            file_bytes=_csv("sample_chase_cc.csv"),
            account_id=account.id,
        )
        response = await _preview_payload(async_db_session, plan)

        assert plan.needs_account is False
        assert response.layout == "Chase Credit Card"
        assert response.account_name == account.name
        assert response.needs_account is False


class TestCsvProfiles:
    def test_amex_charge_lands_negative(self) -> None:
        from app.services.finance.adapters.importers import csv_profiles

        data = _csv("sample_amex.csv")
        profile, index = csv_profiles.detect_profile(data, _profiles())
        assert profile is not None and profile.name == "American Express"
        parsed = csv_profiles.parse_csv(data, profile, header_index=index)
        charge = next(p for p in parsed if p.name == "GOURMET RESTAURANT")
        assert charge.amount == -12050  # +120.50 reported -> outflow negative

    def test_chase_cc_detects_and_signs(self) -> None:
        from app.services.finance.adapters.importers import csv_profiles

        data = _csv("sample_chase_cc.csv")
        profile, index = csv_profiles.detect_profile(data, _profiles())
        assert profile is not None and profile.name == "Chase Credit Card"
        by_name = {
            p.name: p for p in csv_profiles.parse_csv(data, profile, header_index=index)
        }
        assert by_name["WHOLE FOODS MKT"].amount == -4500  # purchase negative
        assert by_name["ONLINE PAYMENT THANK YOU"].amount == 50000  # payment +

    def test_unknown_header_returns_none(self) -> None:
        from app.services.finance.adapters.importers import csv_profiles

        profile, index = csv_profiles.detect_profile(
            b"Foo,Bar,Baz\n1,2,3\n", _profiles()
        )
        assert profile is None and index == -1

    def test_quicken_mac_skips_preamble(self) -> None:
        """Quicken Mac's report CSV has a title + spacer before the header —
        detection scans past them and parses with the outflow-negative sign."""
        from app.services.finance.adapters.importers import csv_profiles

        data = _csv("sample_quicken_mac.csv")
        profile, index = csv_profiles.detect_profile(data, _profiles())
        assert profile is not None and profile.name == "Quicken Mac Register"
        assert index == 2  # header is the 3rd line
        parsed = csv_profiles.parse_csv(data, profile, header_index=index)
        assert len(parsed) == 3
        by_name = {p.name: p for p in parsed}
        assert by_name["Mortgage Co"].amount == -122300  # -1,223.00
        assert by_name["Pension Deposit"].amount == 97035  # +970.35 income
        assert by_name["City Water"].check_number == "1055"
        # Running balance is captured from the Balance column (raw, unsigned by
        # the amount convention).
        assert by_name["Mortgage Co"].running_balance == 500000  # 5,000.00
        assert by_name["City Water"].running_balance == 592535  # 5,925.35

    def test_quicken_all_transactions_reads_account_column(self) -> None:
        """The 'All Transactions' report is a multi-account layout: each row
        carries its owning account in the Account column -> account_key."""
        from app.services.finance.adapters.importers import csv_profiles

        data = _csv("sample_quicken_all.csv")
        profile, index = csv_profiles.detect_profile(data, _profiles())
        assert profile is not None and profile.name == "Quicken All Transactions"
        parsed = csv_profiles.parse_csv(data, profile, header_index=index)
        assert len(parsed) == 5  # footer summary lines skipped
        assert {p.account_key for p in parsed} == {"CHECKING", "AMEX CARD"}
        checking = [p for p in parsed if p.account_key == "CHECKING"]
        assert any(p.amount == 500000 for p in checking)  # +5,000.00 payroll

    def test_detects_a_layout_that_gained_a_vendor_column(self) -> None:
        """Quicken added a leading "Scheduled" column to the All
        Transactions report. Detection matched on exact column count, so
        one added column rejected the entire file. Parsing addresses
        columns by name, so extras were always harmless - detection now
        accepts a row that carries the full signature plus extras."""
        from app.services.finance.adapters.importers import csv_profiles

        data = _csv("sample_quicken_all_scheduled.csv")
        profile, index = csv_profiles.detect_profile(data, _profiles())
        assert profile is not None and profile.name == "Quicken All Transactions"
        parsed = csv_profiles.parse_csv(data, profile, header_index=index)
        assert len(parsed) == 4
        by_name = {p.name: p for p in parsed}
        # Columns after the inserted one still land in the right fields.
        assert by_name["Employer Payroll"].amount == 500000
        assert by_name["Whole Foods"].account_key == "CHECKING"
        assert by_name["Portasoft"].amount == -3893

    def test_exact_match_wins_over_a_looser_one(self) -> None:
        """A file whose header exactly matches one profile must not be
        claimed by another whose signature merely fits inside it."""
        from app.services.finance.adapters.importers import csv_profiles

        data = _csv("sample_quicken_all.csv")
        profile, _ = csv_profiles.detect_profile(data, list(reversed(_profiles())))
        assert profile is not None and profile.name == "Quicken All Transactions"


class TestInferAccountKind:
    def test_infers_type_and_classification_from_name(self) -> None:
        from app.services.finance.adapters.importers.imports import infer_account_kind

        assert infer_account_kind("CHASE SAVINGS") == ("savings", "asset")
        assert infer_account_kind("TOTAL CHECKING (CHASE)") == ("checking", "asset")
        # "checking" wins over "house" (rule order), so this is a checking asset.
        assert infer_account_kind("House Bedner Checking") == ("checking", "asset")
        assert infer_account_kind("Citizens Bank Mortgage") == ("loan", "liability")
        assert infer_account_kind("READI CASH LOC FLUCTUATING PMT") == (
            "loan",
            "liability",
        )
        assert infer_account_kind("AMEX") == ("credit_card", "liability")
        assert infer_account_kind("Citi Double Cash Card") == (
            "credit_card",
            "liability",
        )
        assert infer_account_kind("IHEART MEDIA 401K") == ("investment", "asset")
        assert infer_account_kind("House Bedner") == ("property", "asset")
        # A conventional mortgage is a loan/liability.
        assert infer_account_kind("CONVENTIONAL") == ("loan", "liability")
        # Unrecognized -> generic asset for the user to reclassify.
        assert infer_account_kind("Brokerage Placeholder XYZ") == (
            "brokerage",
            "asset",
        )
        assert infer_account_kind("Mystery Account") == ("other_asset", "asset")


class TestCsvImport:
    @pytest.mark.asyncio
    async def test_import_records_profile_and_signs(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select

        from app.services.finance.models import FinanceImportBatch

        account = await _account(async_db_session)
        await _seed_csv_profiles(async_db_session)
        result = await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="amex.csv",
            file_bytes=_csv("sample_amex.csv"),
            account_id=account.id,
        )
        assert result.rows_inserted == 2
        batch = (
            await async_db_session.exec(
                select(FinanceImportBatch).where(
                    FinanceImportBatch.id == result.batch_id
                )
            )
        ).one()
        assert batch.import_profile_id is not None  # detected profile recorded

        txns, _ = await svc.list_transactions(owner_user_id=1, account_id=account.id)
        assert any(t.amount == -12050 for t in txns)  # the AMEX charge

    @pytest.mark.asyncio
    async def test_scheduled_rows_are_recorded_but_never_ledgered(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Quicken can export SCHEDULED bills alongside posted ones. They are
        money that has not moved, so they must not reach the ledger - they
        would shift balances and double-count against the projection, which
        already walks the same bills forward from recurring streams.

        Both signals matter: an "Overdue" scheduled row is dated in the
        PAST, so a future-date rule alone would let it through."""
        from sqlmodel import select

        from app.services.finance.models import FinanceImportBatchRow

        await _seed_csv_profiles(async_db_session)
        result = await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="all_scheduled.csv",
            file_bytes=_csv("sample_quicken_all_scheduled.csv"),
        )
        # 2 posted rows in; the "Scheduled" (future) and "Overdue" (PAST
        # dated) rows are both held out.
        assert result.rows_inserted == 2
        assert result.rows_skipped == 2

        txns, total = await svc.list_transactions(owner_user_id=1)
        assert total == 2
        names = {t.name for t in txns}
        assert "Portasoft" not in names  # scheduled, future-dated
        assert "Verizon Wireless" not in names  # scheduled, PAST-dated

        # Skipped rows are recorded, not silently dropped.
        rows = (
            await async_db_session.exec(
                select(FinanceImportBatchRow).where(
                    FinanceImportBatchRow.import_batch_id == result.batch_id,
                    FinanceImportBatchRow.parsed_status == "skipped",
                )
            )
        ).all()
        assert len(rows) == 2
        assert all("scheduled" in (r.reason or "") for r in rows)

    @pytest.mark.asyncio
    async def test_scheduled_rows_do_not_shift_real_rows_hashes(
        self, async_db_session: AsyncSession
    ) -> None:
        """Held-out rows must be out of the HASH grouping too. If they
        shaped the within-day ordinals, real rows would hash differently
        with and without them, and a later import would duplicate them."""
        from datetime import date as date_cls
        from datetime import timedelta

        account = await _account(async_db_session)
        posted = ParsedTransaction(
            date=date_cls(2026, 7, 1),
            amount=-4500,
            name="Corner Bistro",
            source="csv",
        )
        scheduled_twin = ParsedTransaction(
            date=date_cls(2026, 7, 1),
            amount=-4500,
            name="Corner Bistro",
            source="csv",
            is_scheduled=True,
        )
        first = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="a.csv",
            file_bytes=b"with scheduled twin",
            parsed=[posted, scheduled_twin],
            default_account_id=account.id,
        )
        assert first.rows_inserted == 1
        assert first.rows_skipped == 1

        # The same posted row again, this time with no scheduled sibling:
        # it must hash identically and read as a duplicate.
        second = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="b.csv",
            file_bytes=b"without scheduled twin",
            parsed=[
                ParsedTransaction(
                    date=date_cls(2026, 7, 1),
                    amount=-4500,
                    name="Corner Bistro",
                    source="csv",
                )
            ],
            default_account_id=account.id,
        )
        assert second.rows_duplicate == 1
        assert second.rows_inserted == 0

        # A future-dated row is held out even with no "scheduled" flag, for
        # sources that carry no such column.
        third = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="c.csv",
            file_bytes=b"future row",
            parsed=[
                ParsedTransaction(
                    date=date_cls.today() + timedelta(days=30),
                    amount=-1000,
                    name="Next month rent",
                    source="csv",
                )
            ],
            default_account_id=account.id,
        )
        assert third.rows_skipped == 1
        assert third.rows_inserted == 0

    @pytest.mark.asyncio
    async def test_import_sets_current_balance_from_running_balance(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A file with a running-balance column (Quicken Mac) sets the account's
        current_balance to the latest-dated row's balance — so net worth
        reflects the import with no separate valuation."""
        from datetime import date

        account = await _account(async_db_session)
        await _seed_csv_profiles(async_db_session)
        await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="quicken.csv",
            file_bytes=_csv("sample_quicken_mac.csv"),
            account_id=account.id,
        )
        refreshed = await svc.get_account(account.id, owner_user_id=1)
        assert refreshed is not None
        # Latest date is 7/3/2026 (City Water), balance 5,925.35 — not file
        # order (the 8/1 rows come first) and not the largest balance.
        assert refreshed.current_balance == 592535
        assert refreshed.balance_as_of is not None
        assert refreshed.balance_as_of.date() == date(2026, 7, 3)

    @pytest.mark.asyncio
    async def test_multi_account_csv_auto_creates_and_routes(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """A multi-account report imports with no account_id: rows route to
        per-name accounts, auto-creating the ones that don't exist yet."""
        await _seed_csv_profiles(async_db_session)
        result = await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="all.csv",
            file_bytes=_csv("sample_quicken_all.csv"),
            account_id=None,  # no single target — the file self-routes
        )
        assert result.rows_inserted == 5

        accounts, _ = await svc.list_accounts(owner_user_id=1)
        by_name = {a.name: a for a in accounts}
        assert {"CHECKING", "AMEX CARD"} <= set(by_name)

        _, checking_total = await svc.list_transactions(
            owner_user_id=1, account_id=by_name["CHECKING"].id
        )
        _, amex_total = await svc.list_transactions(
            owner_user_id=1, account_id=by_name["AMEX CARD"].id
        )
        assert checking_total == 2
        # 2 visible: the two identical $45 rows (per-account within-day
        # ordinals keep them distinct rather than colliding as one
        # duplicate). The $200 "Amex Payment" row is categorized Transfer,
        # so the reconcile pass flags it and the register hides it by
        # default, the same as a paired leg - it is money moving between
        # accounts, not card spend.
        assert amex_total == 2
        all_rows, amex_all = await svc.list_transactions(
            owner_user_id=1,
            account_id=by_name["AMEX CARD"].id,
            include_transfers=True,
        )
        assert amex_all == 3
        flagged = [t for t in all_rows if t.is_transfer]
        assert [t.name for t in flagged] == ["Amex Payment"]
        # Type/classification inferred from the name: a card is a liability,
        # a "CHECKING" account is a checking asset.
        assert by_name["AMEX CARD"].classification == "liability"
        assert by_name["AMEX CARD"].account_type == "credit_card"
        assert by_name["CHECKING"].classification == "asset"
        assert by_name["CHECKING"].account_type == "checking"

    @pytest.mark.asyncio
    async def test_multi_account_reimport_dedups_without_duplicate_accounts(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        """Re-importing matches existing accounts by name (no duplicates) and
        the per-account LANE-2 hash catches every row as a duplicate."""
        await _seed_csv_profiles(async_db_session)
        data = _csv("sample_quicken_all.csv")
        await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="all.csv",
            file_bytes=data,
            account_id=None,
        )
        # Trailing newline -> new file sha, same content, so the sha
        # short-circuit is bypassed and every row is re-checked per account.
        result = await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="all2.csv",
            file_bytes=data + b"\n",
            account_id=None,
        )
        assert result.rows_inserted == 0
        assert result.rows_duplicate == 5

        accounts, _ = await svc.list_accounts(owner_user_id=1)
        assert sum(1 for a in accounts if a.name == "AMEX CARD") == 1

    @pytest.mark.asyncio
    async def test_unknown_header_marks_failed_batch(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select

        from app.services.finance.adapters.importers.csv_profiles import (
            UnknownCsvLayoutError,
        )
        from app.services.finance.models import FinanceImportBatch

        account = await _account(async_db_session)
        await _seed_csv_profiles(async_db_session)
        with pytest.raises(UnknownCsvLayoutError):
            await imports.import_csv(
                async_db_session,
                owner_user_id=1,
                file_name="weird.csv",
                file_bytes=b"Foo,Bar,Baz\n1,2,3\n",
                account_id=account.id,
            )
        failed = (
            await async_db_session.exec(
                select(FinanceImportBatch).where(FinanceImportBatch.status == "failed")
            )
        ).all()
        assert failed and failed[0].rows_total == 0
        _, total = await svc.list_transactions(owner_user_id=1, account_id=account.id)
        assert total == 0  # nothing written on an unknown layout

    @pytest.mark.asyncio
    async def test_reimport_zero_dupes(self, async_db_session: AsyncSession) -> None:
        account = await _account(async_db_session)
        await _seed_csv_profiles(async_db_session)
        data = _csv("sample_chase_checking.csv")
        await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="chk.csv",
            file_bytes=data,
            account_id=account.id,
        )
        second = await imports.import_csv(
            async_db_session,
            owner_user_id=1,
            file_name="chk.csv",
            file_bytes=data,
            account_id=account.id,
        )
        assert second.rows_inserted == 0


# ---------------------------------------------------------------------------
# Pre-commit preview + user-category guard — FIN-33
# ---------------------------------------------------------------------------


def _qif_edited(extra_row: bool = False) -> bytes:
    """``sample_quicken.qif`` with the Blue Bottle row edited in the source
    app (renamed payee, re-categorized) — an unambiguous LANE-3 update on
    re-import — plus, optionally, one genuinely new row."""
    data = _qif().replace(b"PBlue Bottle Coffee", b"PBlue Bottle Cafe")
    data = data.replace(b"Mmorning\nLDining", b"Mmorning\nLCoffee Shops")
    assert b"PBlue Bottle Cafe" in data and b"LCoffee Shops" in data
    if extra_row:
        data += b"D07/20/2026\nT-15.00\nPNew Bakery\nLDining\n^\n"
    return data


class TestImportPreviewAndCategoryGuard:
    """FIN-33: a preview is the commit's own plan, and the commit never
    overwrites a category the user set by hand."""

    async def _baseline(
        self, session: AsyncSession
    ) -> tuple[FinanceAccount, int | None]:
        account = await _account(session)
        first = await imports.import_file(
            session,
            owner_user_id=1,
            file_name="q.qif",
            file_bytes=_qif(),
            account_id=account.id,
        )
        assert first.rows_inserted == 8
        return account, first.batch_id

    async def _blue_bottle(self, session: AsyncSession):
        from sqlmodel import select as sql_select

        from app.services.finance.models import FinanceTransaction

        return (
            await session.exec(
                sql_select(FinanceTransaction).where(
                    FinanceTransaction.name == "Blue Bottle Coffee"
                )
            )
        ).first()

    @pytest.mark.asyncio
    async def test_user_set_category_survives_lane3_edit(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select as sql_select

        from app.services.finance.models import FinanceImportBatchRow

        account, _ = await self._baseline(async_db_session)
        target = await self._blue_bottle(async_db_session)
        assert target is not None
        user_category = await svc.get_or_create_category_from_hint("Coffee Fund")
        target.category_id = user_category.id
        target.category_source = "user"
        async_db_session.add(target)
        await async_db_session.flush()

        edited = _qif_edited()
        # The preview flags the decision before anything is written...
        preview = await imports.preview_file(
            async_db_session,
            owner_user_id=1,
            file_name="q2.qif",
            file_bytes=edited,
            account_id=account.id,
        )
        planned = [row for row in preview.rows if row.status == "updated"]
        assert len(planned) == 1
        assert planned[0].category_action == "kept"
        assert target.category_id == user_category.id  # preview wrote nothing

        # ...and the commit honours the same plan.
        result = await imports.import_file(
            async_db_session,
            owner_user_id=1,
            file_name="q2.qif",
            file_bytes=edited,
            account_id=account.id,
        )
        assert result.rows_updated == 1
        assert target.name == "Blue Bottle Cafe"  # labels still update
        assert target.category_id == user_category.id  # the category does not
        assert target.category_source == "user"
        reason = (
            await async_db_session.exec(
                sql_select(FinanceImportBatchRow.reason).where(
                    FinanceImportBatchRow.import_batch_id == result.batch_id,
                    FinanceImportBatchRow.parsed_status == "updated",
                )
            )
        ).first()
        assert imports.CATEGORY_KEPT_NOTE in (reason or "")

    @pytest.mark.asyncio
    async def test_rule_set_category_still_updates(
        self, async_db_session: AsyncSession
    ) -> None:
        account, _ = await self._baseline(async_db_session)
        target = await self._blue_bottle(async_db_session)
        assert target is not None
        assert target.category_source == "rule"  # came from the import hint
        category_before = target.category_id

        result = await imports.import_file(
            async_db_session,
            owner_user_id=1,
            file_name="q2.qif",
            file_bytes=_qif_edited(),
            account_id=account.id,
        )
        assert result.rows_updated == 1
        assert target.category_id != category_before  # Coffee Shops now
        assert target.category_source == "rule"

    @pytest.mark.asyncio
    async def test_preview_counts_match_commit_and_write_nothing(
        self, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select as sql_select

        from app.services.finance.models import (
            FinanceCategory,
            FinanceImportBatch,
            FinanceTransaction,
        )

        account, _ = await self._baseline(async_db_session)
        edited = _qif_edited(extra_row=True)

        async def _row_counts() -> tuple[int, int, int, int]:
            async def _count(model) -> int:
                return len((await async_db_session.exec(sql_select(model))).all())

            return (
                await _count(FinanceImportBatch),
                await _count(FinanceTransaction),
                await _count(FinanceCategory),
                await _count(FinanceAccount),
            )

        before = await _row_counts()
        preview = await imports.preview_file(
            async_db_session,
            owner_user_id=1,
            file_name="q2.qif",
            file_bytes=edited,
            account_id=account.id,
        )
        assert await _row_counts() == before  # a preview is a pure read
        assert preview.new_category_hints == ["Coffee Shops"]

        result = await imports.import_file(
            async_db_session,
            owner_user_id=1,
            file_name="q2.qif",
            file_bytes=edited,
            account_id=account.id,
        )
        assert result.rows_inserted == 1 and result.rows_updated == 1
        assert (
            preview.count("inserted"),
            preview.count("updated"),
            preview.count("duplicate"),
            preview.count("skipped"),
            preview.count("error"),
        ) == (
            result.rows_inserted,
            result.rows_updated,
            result.rows_duplicate,
            result.rows_skipped,
            result.rows_error,
        )

    @pytest.mark.asyncio
    async def test_preview_of_identical_file_short_circuits(
        self, async_db_session: AsyncSession
    ) -> None:
        account, batch_id = await self._baseline(async_db_session)
        preview = await imports.preview_file(
            async_db_session,
            owner_user_id=1,
            file_name="q.qif",
            file_bytes=_qif(),
            account_id=account.id,
        )
        assert preview.identical_batch_id == batch_id
        assert preview.rows == []
        assert preview.rows_total == 8

    @pytest.mark.asyncio
    async def test_preview_multi_account_csv_creates_no_accounts(
        self, async_db_session: AsyncSession
    ) -> None:
        from sqlmodel import select as sql_select

        await _seed_csv_profiles(async_db_session)
        data = _csv("sample_quicken_all.csv")
        preview = await imports.preview_file(
            async_db_session,
            owner_user_id=1,
            file_name="all.csv",
            file_bytes=data,
        )
        assert preview.new_accounts  # the file names accounts we don't have
        assert all(row.account_id is None or row.account_id < 0 for row in preview.rows)
        accounts = (await async_db_session.exec(sql_select(FinanceAccount))).all()
        assert accounts == []  # naming an account is not creating one


class TestDoubleSubmitLandsOnTheFirstBatch:
    """Two submissions of the same bytes in flight at once (a double-click
    on Import): the early identical-file check can MISS - the first run's
    commit isn't visible yet - and the loser then crashed the whole job on
    ``uq_finance_importbatch_file`` (confirmed live). The batch insert now
    falls back to the winner instead of raising."""

    @pytest.mark.asyncio
    async def test_the_racing_loser_returns_the_winners_batch(
        self, svc: FinanceService, async_db_session: AsyncSession, monkeypatch
    ) -> None:
        from datetime import date as date_cls

        account = await svc.create_manual_account(
            owner_user_id=1,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        parsed = [
            ParsedTransaction(
                date=date_cls(2026, 8, 1),
                amount=-5_000,
                source="csv",
                name="Coffee",
                account_key=None,
            )
        ]
        first = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="export.csv",
            file_bytes=b"same-bytes",
            parsed=parsed,
            default_account_id=account.id,
        )
        assert first.rows_inserted == 1

        # Simulate the race window: the second run's early check misses
        # (as if the first commit weren't visible yet), so it walks into
        # the unique constraint - and must land on the winner, not raise.
        real = imports._prior_batch
        calls = {"n": 0}

        async def miss_once(db, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real(db, **kwargs)

        monkeypatch.setattr(imports, "_prior_batch", miss_once)

        second = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="export.csv",
            file_bytes=b"same-bytes",
            parsed=parsed,
            default_account_id=account.id,
        )

        assert second.batch_id == first.batch_id
        assert second.rows_inserted == 0
        assert second.rows_duplicate == second.rows_total
        # And nothing was double-written.
        _rows, total = await svc.list_transactions(owner_user_id=1)
        assert total == 1


class TestDeletedTransactionStaysDeleted:
    """Deleting a transaction is a standing decision too: re-importing the
    same file must not resurrect the row. Same class of trap as the
    removed-account guard above - both dedup lanes are partial indexes on
    ``deleted_at IS NULL``, so without this the exact same row re-inserts
    as "new"."""

    @pytest.mark.asyncio
    async def test_a_deleted_row_replans_as_ignored(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        from datetime import date as date_cls

        account = await svc.create_manual_account(
            owner_user_id=1,
            name="TOTAL CHECKING",
            account_type="checking",
            classification="asset",
        )
        parsed = [
            ParsedTransaction(
                date=date_cls(2026, 8, 1),
                amount=-5_000,
                source="csv",
                name="Coffee",
                account_key="TOTAL CHECKING",
            ),
            ParsedTransaction(
                date=date_cls(2026, 8, 2),
                amount=-70_000,
                source="csv",
                name="Car payment",
                account_key="TOTAL CHECKING",
            ),
        ]
        first = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="first.csv",
            file_bytes=b"first-pass-bytes",
            parsed=parsed,
            auto_create_accounts=True,
        )
        assert first.rows_inserted == 2

        rows, _total = await svc.list_transactions(owner_user_id=1)
        coffee = next(r for r in rows if r.name == "Coffee")
        await svc.soft_delete_transactions([coffee.id], owner_user_id=1)

        plan = await imports.plan_transactions(
            async_db_session,
            owner_user_id=1,
            parsed=parsed,
            auto_create_accounts=True,
        )

        ignored = [
            r for r in plan.rows if r.status == "skipped" and r.reason is not None
        ]
        assert len(ignored) == 1
        assert "deleted" in (ignored[0].reason or "")
        assert plan.count("duplicate") == 1  # the untouched row still dedups
        assert plan.count("inserted") == 0

        # And the commit executes the same verdict: nothing comes back.
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="second.csv",
            file_bytes=b"second-pass-bytes",
            parsed=parsed,
            auto_create_accounts=True,
        )
        assert result.rows_inserted == 0
        assert result.rows_ignored == 1
        _rows, total = await svc.list_transactions(owner_user_id=1)
        assert total == 1
        assert account.id is not None


class TestRemovedAccountStaysRemoved:
    """Deleting an account is a standing decision: a later import of the
    same file must not resurrect it. Its rows plan (and ingest) as
    ignored - visibly counted, never written, and the account is not
    re-minted."""

    @pytest.mark.asyncio
    async def test_rows_for_a_removed_account_are_ignored(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        keep = await svc.create_manual_account(
            owner_user_id=1,
            name="TOTAL CHECKING",
            account_type="checking",
            classification="asset",
        )
        audi = await svc.create_manual_account(
            owner_user_id=1,
            name="X017 AUDI A6",
            account_type="loan",
            classification="liability",
        )
        await svc.soft_delete_account(audi.id, owner_user_id=1)

        from datetime import date as date_cls

        parsed = [
            ParsedTransaction(
                date=date_cls(2026, 8, 1),
                amount=-5_000,
                source="csv",
                name="Coffee",
                account_key="TOTAL CHECKING",
            ),
            ParsedTransaction(
                date=date_cls(2026, 8, 2),
                amount=-70_000,
                source="csv",
                name="Car payment",
                account_key="X017 AUDI A6",
            ),
        ]
        plan = await imports.plan_transactions(
            async_db_session,
            owner_user_id=1,
            parsed=parsed,
            auto_create_accounts=True,
        )
        # The removed account is neither resurrected nor re-minted...
        assert "X017 AUDI A6" not in plan.new_accounts
        assert plan.removed_accounts == ["X017 AUDI A6"]
        assert plan.count("inserted") == 1
        ignored = [
            r
            for r in plan.rows
            if r.status == "skipped" and r.account_key == "X017 AUDI A6"
        ]
        assert len(ignored) == 1
        assert "removed" in (ignored[0].reason or "")

        # ...and ingest executes the same verdict.
        result = await imports.ingest_transactions(
            async_db_session,
            owner_user_id=1,
            source_type="csv",
            file_name="requick.csv",
            file_bytes=b"requick-test-bytes",
            parsed=parsed,
            auto_create_accounts=True,
        )
        assert result.rows_inserted == 1
        assert result.rows_ignored == 1
        accounts, total = await svc.list_accounts(owner_user_id=1)
        assert [a.name for a in accounts] == ["TOTAL CHECKING"]
        assert keep.id is not None


class TestFacadeDelegation:
    """The API layer drives imports through ``FinanceService``, so the facade
    must expose the pipeline; ``importers.imports`` is package-internal."""

    @pytest.mark.asyncio
    async def test_preview_and_import_via_facade(
        self, svc: FinanceService, async_db_session: AsyncSession
    ) -> None:
        account = await _account(async_db_session)
        plan = await svc.preview_file(
            owner_user_id=1,
            file_name="q.qif",
            file_bytes=_qif(),
            account_id=account.id,
        )
        assert plan.rows_total == 8
        result = await svc.import_file(
            owner_user_id=1,
            file_name="q.qif",
            file_bytes=_qif(),
            account_id=account.id,
        )
        assert result.rows_inserted == 8


class TestParseRunsOffTheEventLoop:
    """Parsing up to 10 MB of text is the import's one big sync CPU chunk.

    On the loop it starves everything sharing the process — health polls
    time out and the job's own SSE stream drops — so both entry points
    must hand the parse to a worker thread.
    """

    @staticmethod
    def _spy(record: list) -> object:
        import threading

        def fake_parse(file_name: str | None, file_bytes: bytes):
            record.append(threading.current_thread())
            return "qfx", []

        return fake_parse

    @pytest.mark.asyncio
    async def test_preview_parses_in_a_thread(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading

        seen: list[threading.Thread] = []
        from app.services.finance.adapters.importers import preview

        # The preview binds the parser at import time in its own module.
        monkeypatch.setattr(preview, "_parse_by_extension", self._spy(seen))
        await imports.preview_file(
            async_db_session, owner_user_id=1, file_name="a.qfx", file_bytes=b"x"
        )
        assert seen and seen[0] is not threading.main_thread()

    @pytest.mark.asyncio
    async def test_import_parses_in_a_thread(
        self, async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import threading

        seen: list[threading.Thread] = []
        monkeypatch.setattr(imports, "_parse_by_extension", self._spy(seen))
        account = await _account(async_db_session)
        await imports.import_file(
            async_db_session,
            owner_user_id=1,
            file_name="a.qfx",
            file_bytes=b"x",
            account_id=account.id,
        )
        assert seen and seen[0] is not threading.main_thread()
