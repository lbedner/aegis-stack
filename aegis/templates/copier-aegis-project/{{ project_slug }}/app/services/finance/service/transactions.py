"""The register: transactions, splits and tags.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from datetime import date

from app.services.finance.constants import Provider
from app.services.finance.domains.ledger import (
    queries as ledger_queries,
)
from app.services.finance.domains.ledger import (
    splits,
    transactions,
)
from app.services.finance.models import (
    FinanceTag,
    FinanceTransaction,
    FinanceTransactionSplit,
)
from app.services.finance.schemas import (
    CashflowMonth,
    PayeeTotal,
    SplitPart,
)
from app.services.finance.service.base import FinanceServiceBase
from app.services.finance.utils import DEFAULT_CURRENCY


class TransactionsMixin(FinanceServiceBase):
    """The register: transactions, splits and tags."""

    async def transaction_exists(
        self,
        *,
        account_id: int,
        source: str,
        external_id: str | None = None,
        import_hash: str | None = None,
    ) -> bool:
        return await transactions.transaction_exists(
            self.db,
            account_id=account_id,
            source=source,
            external_id=external_id,
            import_hash=import_hash,
        )

    async def find_transaction(
        self,
        *,
        account_id: int,
        source: str,
        external_id: str | None = None,
        import_hash: str | None = None,
    ) -> FinanceTransaction | None:
        return await transactions.find_transaction(
            self.db,
            account_id=account_id,
            source=source,
            external_id=external_id,
            import_hash=import_hash,
        )

    async def create_transaction(
        self,
        *,
        account_id: int,
        amount: int,
        txn_date: date,
        owner_user_id: int | None = None,
        name: str | None = None,
        source: str = Provider.MANUAL,
        external_id: str | None = None,
        external_id_source: str | None = None,
        import_hash: str | None = None,
        within_day_ordinal: int = 0,
        import_batch_id: int | None = None,
        connection_id: int | None = None,
        raw_amount: int | None = None,
        raw_sign_convention: str | None = None,
        original_description: str | None = None,
        memo: str | None = None,
        check_number: str | None = None,
        currency: str = DEFAULT_CURRENCY,
        category_id: int | None = None,
        category_source: str = "unset",
        is_split: bool = False,
        pending: bool = False,
        pending_provider_id: str | None = None,
    ) -> FinanceTransaction:
        return await transactions.create_transaction(
            self.db,
            account_id=account_id,
            amount=amount,
            txn_date=txn_date,
            owner_user_id=owner_user_id,
            name=name,
            source=source,
            external_id=external_id,
            external_id_source=external_id_source,
            import_hash=import_hash,
            within_day_ordinal=within_day_ordinal,
            import_batch_id=import_batch_id,
            connection_id=connection_id,
            raw_amount=raw_amount,
            raw_sign_convention=raw_sign_convention,
            original_description=original_description,
            memo=memo,
            check_number=check_number,
            currency=currency,
            category_id=category_id,
            category_source=category_source,
            is_split=is_split,
            pending=pending,
            pending_provider_id=pending_provider_id,
        )

    async def create_split(
        self,
        *,
        parent_transaction_id: int,
        amount: int,
        owner_user_id: int | None = None,
        category_id: int | None = None,
        memo: str | None = None,
        sort_order: int = 0,
        currency: str = DEFAULT_CURRENCY,
    ) -> FinanceTransactionSplit:
        return await transactions.create_split(
            self.db,
            parent_transaction_id=parent_transaction_id,
            amount=amount,
            owner_user_id=owner_user_id,
            category_id=category_id,
            memo=memo,
            sort_order=sort_order,
            currency=currency,
        )

    async def split_transaction(
        self,
        transaction_id: int,
        parts: list[SplitPart],
        *,
        owner_user_id: int | None = None,
    ) -> list[FinanceTransactionSplit]:
        return await splits.split_transaction(
            self.db, transaction_id, parts, owner_user_id=owner_user_id
        )

    async def unsplit_transaction(
        self, transaction_id: int, *, owner_user_id: int | None = None
    ) -> int:
        return await splits.unsplit_transaction(
            self.db, transaction_id, owner_user_id=owner_user_id
        )

    async def transaction_splits(
        self, transaction_ids: list[int]
    ) -> dict[int, list[FinanceTransactionSplit]]:
        return await ledger_queries.splits_for_parents(self.db, transaction_ids)

    async def get_or_create_tag(
        self, name: str, *, owner_user_id: int | None = None
    ) -> FinanceTag:
        return await transactions.get_or_create_tag(
            self.db,
            name,
            owner_user_id=owner_user_id,
        )

    async def list_tags(
        self, *, owner_user_id: int | None = None
    ) -> list[tuple[FinanceTag, int]]:
        return await transactions.list_tags(self.db, owner_user_id=owner_user_id)

    async def tag_transactions(
        self, transaction_ids: list[int], name: str, *, owner_user_id: int | None = None
    ) -> FinanceTag:
        return await transactions.tag_transactions(
            self.db,
            transaction_ids,
            name,
            owner_user_id=owner_user_id,
        )

    async def untag_transactions(
        self,
        transaction_ids: list[int],
        tag_id: int,
        *,
        owner_user_id: int | None = None,
    ) -> int:
        return await transactions.untag_transactions(
            self.db,
            transaction_ids,
            tag_id,
            owner_user_id=owner_user_id,
        )

    async def soft_delete_transactions(
        self, transaction_ids: list[int], *, owner_user_id: int | None = None
    ) -> int:
        return await transactions.soft_delete_transactions(
            self.db,
            transaction_ids,
            owner_user_id=owner_user_id,
        )

    async def transaction_tags(
        self, transaction_ids: list[int] | set[int]
    ) -> dict[int, list[FinanceTag]]:
        return await transactions.transaction_tags(self.db, transaction_ids)

    async def uncategorized_transactions(
        self,
        *,
        owner_user_id: int | None = None,
        limit: int | None = 7,
        query: str | None = None,
        from_date: date | None = None,
        account_ids: list[int] | None = None,
    ) -> tuple[list[FinanceTransaction], int]:
        return await transactions.uncategorized_transactions(
            self.db,
            owner_user_id=owner_user_id,
            limit=limit,
            query=query,
            from_date=from_date,
            account_ids=account_ids,
        )

    async def top_payees(
        self,
        *,
        owner_user_id: int | None = None,
        days: int = 90,
        limit: int = 8,
    ) -> list[PayeeTotal]:
        return await transactions.top_payees(
            self.db,
            owner_user_id=owner_user_id,
            days=days,
            limit=limit,
        )

    async def monthly_cashflow(
        self,
        *,
        owner_user_id: int | None = None,
        months: int = 6,
        today: date | None = None,
        account_ids: list[int] | None = None,
    ) -> list[CashflowMonth]:
        return await transactions.monthly_cashflow(
            self.db,
            owner_user_id=owner_user_id,
            months=months,
            today=today,
            account_ids=account_ids,
        )

    async def get_transaction(
        self, transaction_id: int, *, owner_user_id: int | None = None
    ) -> FinanceTransaction | None:
        return await transactions.get_transaction(
            self.db,
            transaction_id,
            owner_user_id=owner_user_id,
        )

    async def transactions_by_ids(
        self, ids: list[int]
    ) -> dict[int, FinanceTransaction]:
        return await transactions.transactions_by_ids(self.db, ids)

    async def list_transactions(
        self,
        *,
        owner_user_id: int | None = None,
        account_id: int | None = None,
        account_ids: list[int] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        category_id: int | None = None,
        merchant_id: int | None = None,
        without_merchant: bool = False,
        tag_id: int | None = None,
        query: str | None = None,
        include_transfers: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FinanceTransaction], int]:
        # Default view: not soft-deleted, and never the losing side of a dedup.
        # Also hide transactions whose account was removed/disconnected — the
        # rows are kept for history + re-link reconciliation, but shouldn't show
        # in the register once the account is gone. Paired transfer legs are
        # hidden by default (``include_transfers``) so a checking->card payment
        # doesn't show as two lines of spend/income.
        return await transactions.list_transactions(
            self.db,
            owner_user_id=owner_user_id,
            account_id=account_id,
            account_ids=account_ids,
            from_date=from_date,
            to_date=to_date,
            category_id=category_id,
            merchant_id=merchant_id,
            without_merchant=without_merchant,
            tag_id=tag_id,
            query=query,
            include_transfers=include_transfers,
            page=page,
            page_size=page_size,
        )
