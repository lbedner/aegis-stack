"""File import: upload, preview, batches.

One sub-router of the finance API (see ``router.py``, the aggregator).
"""

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse

from app.components.backend.api.finance.base import _MAX_IMPORT_BYTES, _NOT_FOUND
from app.components.backend.api.finance.declare import _preview_payload
from app.core.db import get_async_session as _job_session
from app.services.finance.adapters.importers import (
    csv_profiles,
    imports,
)
from app.services.finance.deps import (
    get_finance_service,
    get_owner_user_id,
)
from app.services.finance.schemas import (
    ImportBatchResponse,
    ImportBatchSummary,
    ImportPreviewResponse,
    ImportResultResponse,
)
from app.services.finance.service import FinanceService
from app.services.system.jobs import (
    JobHandle,
    get_job_runner,
)

router = APIRouter()


# -- Imports -----------------------------------------------------------------


def _import_result_payload(result: imports.ImportResult) -> dict:
    """The ImportResultResponse fields, as the dict both contracts share."""
    return ImportResultResponse(
        batch_id=result.batch_id,
        rows_total=result.rows_total,
        rows_inserted=result.rows_inserted,
        rows_updated=result.rows_updated,
        rows_duplicate=result.rows_duplicate,
        rows_error=result.rows_error,
        rows_skipped=result.rows_skipped,
        rows_ignored=result.rows_ignored,
    ).model_dump()


@router.post("/import", response_model=None)
async def import_file(
    file: UploadFile = File(...),
    account_id: int | None = None,
    background: bool = False,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ImportResultResponse | JSONResponse:
    """Upload an OFX/QFX/QIF/CSV file and ingest it under a reversible batch.

    Dispatch is by file extension. QIF/CSV need an ``account_id`` (they carry no
    account info); OFX can resolve its own. Duplicate rows are deduped; an
    identical re-upload short-circuits via the file hash.

    With ``background=true`` the upload is validated synchronously, the
    ingest (row inserts + inline reconciliation rules - the long part) runs
    as an in-process job, and the response is ``202 {"job_id": ...}``.
    Follow ``GET /api/v1/jobs/{id}/events``; the terminal event's ``result``
    carries the same fields as the synchronous response.
    """
    data = await file.read()
    if len(data) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 10 MB).",
        )
    if account_id is not None:
        account = await service.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            )

    if background:
        file_name = file.filename

        async def work(handle: JobHandle) -> dict:
            handle.set_label(f"Importing {file_name}...")
            async with _job_session() as session:
                result = await FinanceService(session).import_file(
                    owner_user_id=owner_user_id,
                    file_name=file_name,
                    file_bytes=data,
                    account_id=account_id,
                )
                await session.commit()
            return _import_result_payload(result)

        job_id = get_job_runner().start(
            f"finance-import:{file_name}", work, label=f"Uploading {file_name}..."
        )
        return JSONResponse({"job_id": job_id}, status_code=status.HTTP_202_ACCEPTED)

    try:
        result = await service.import_file(
            owner_user_id=owner_user_id,
            file_name=file.filename,
            file_bytes=data,
            account_id=account_id,
        )
    except imports.UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except csv_profiles.UnknownCsvLayoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:  # e.g. QIF/CSV without an account_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return ImportResultResponse(**_import_result_payload(result))


@router.post("/import/preview", response_model=ImportPreviewResponse)
async def preview_import(
    file: UploadFile = File(...),
    account_id: int | None = None,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ImportPreviewResponse:
    """Dry-run an import: what /import would do with this exact file.

    Same params and dispatch as ``POST /import``, produced from the same
    classification the commit executes — but a pure read. No batch row, no
    auto-created accounts or categories, no transaction writes. The client
    shows this, then re-posts the same bytes to ``/import`` to commit.
    """
    data = await file.read()
    if len(data) > _MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 10 MB).",
        )
    if account_id is not None:
        account = await service.get_account(account_id, owner_user_id=owner_user_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND
            )
    try:
        plan = await service.preview_file(
            owner_user_id=owner_user_id,
            file_name=file.filename,
            file_bytes=data,
            account_id=account_id,
        )
    except imports.UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except csv_profiles.UnknownCsvLayoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:  # e.g. QIF/CSV without an account_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return await _preview_payload(service.db, plan)


@router.get("/import/batches", response_model=list[ImportBatchSummary])
async def list_import_batches(
    page: int = 1,
    page_size: int = 20,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> list[ImportBatchSummary]:
    """The caller's import batches, newest first."""
    batches = await service.list_import_batches(
        owner_user_id=owner_user_id, page=page, page_size=page_size
    )
    return [ImportBatchSummary.from_row(b) for b in batches]


@router.get("/import/batches/{batch_id}", response_model=ImportBatchResponse)
async def get_import_batch(
    batch_id: int,
    service: FinanceService = Depends(get_finance_service),
    owner_user_id: int | None = Depends(get_owner_user_id),
) -> ImportBatchResponse:
    """Batch review: the run's counts plus every parsed row's outcome."""
    batch = await service.get_import_batch(batch_id, owner_user_id=owner_user_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import batch not found"
        )
    rows = await service.list_import_batch_rows(batch_id)
    return ImportBatchResponse.from_batch(batch, rows)
