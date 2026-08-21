"""Import batches and the rows they wrote.

One mixin of the ``FinanceService`` facade: every method here forwards
to the matching domain module as ``module.func(self.db, ...)``.
"""

from __future__ import annotations

from app.services.finance.adapters.importers import imports
from app.services.finance.models import (
    FinanceImportBatch,
    FinanceImportBatchRow,
)
from app.services.finance.service.base import FinanceServiceBase


class ImportsMixin(FinanceServiceBase):
    """Import batches and the rows they wrote."""

    async def get_import_batch(
        self, batch_id: int, *, owner_user_id: int | None = None
    ) -> FinanceImportBatch | None:
        # finance_import_batch.owner_user_id is NOT NULL; standalone uses 0.
        return await imports.get_import_batch(
            self.db,
            batch_id,
            owner_user_id=owner_user_id,
        )

    async def list_import_batches(
        self,
        *,
        owner_user_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[FinanceImportBatch]:
        return await imports.list_import_batches(
            self.db,
            owner_user_id=owner_user_id,
            page=page,
            page_size=page_size,
        )

    async def list_import_batch_rows(
        self, batch_id: int
    ) -> list[FinanceImportBatchRow]:
        return await imports.list_import_batch_rows(self.db, batch_id)

    async def preview_file(
        self,
        *,
        owner_user_id: int | None,
        file_name: str | None,
        file_bytes: bytes,
        account_id: int | None = None,
    ) -> imports.ImportPlan:
        return await imports.preview_file(
            self.db,
            owner_user_id=owner_user_id,
            file_name=file_name,
            file_bytes=file_bytes,
            account_id=account_id,
        )

    async def import_file(
        self,
        *,
        owner_user_id: int | None,
        file_name: str | None,
        file_bytes: bytes,
        account_id: int | None = None,
    ) -> imports.ImportResult:
        return await imports.import_file(
            self.db,
            owner_user_id=owner_user_id,
            file_name=file_name,
            file_bytes=file_bytes,
            account_id=account_id,
        )
