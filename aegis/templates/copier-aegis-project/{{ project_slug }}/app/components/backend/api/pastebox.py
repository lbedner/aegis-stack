"""The pastebox endpoints: stage a pasted image, drain the staged set.

The POST side is called by the dashboard's injected capture script
(see ``middleware/paste_capture.py``); the drain side by whichever
consumer surface is polling (chat's attachment bar). Generic on
purpose - nothing here knows what a consumer does with the image.
"""

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core.pastebox import pastebox

router = APIRouter(prefix="/pastebox", tags=["pastebox"])

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_BYTES = 10 * 1024 * 1024


class PasteStageResponse(BaseModel):
    staged: int


class PasteDrainResponse(BaseModel):
    items: list[dict[str, str]]
    # Pastes announced but not yet uploaded - the "receiving" indicator.
    incoming: int = 0


@router.post("", response_model=PasteStageResponse)
async def stage_paste(file: UploadFile) -> PasteStageResponse:
    """Stage one pasted image for whichever surface drains next."""
    if (file.content_type or "") not in _IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only images can be pasted, not {file.content_type!r}.",
        )
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Pasted image is larger than 10MB.",
        )
    pastebox.stage(
        media_type=file.content_type or "image/png",
        data=data,
        name=file.filename,
    )
    return PasteStageResponse(staged=1)


@router.post("/incoming", response_model=PasteStageResponse)
async def announce_paste() -> PasteStageResponse:
    """The capture script's pre-upload ping: lets consumers show a
    "receiving" indicator while the image is still in transit."""
    pastebox.mark_incoming()
    return PasteStageResponse(staged=0)


@router.post("/drain", response_model=PasteDrainResponse)
async def drain_pastes() -> PasteDrainResponse:
    """Hand over (and clear) everything staged - drain-once."""
    return PasteDrainResponse(items=pastebox.drain(), incoming=pastebox.incoming())
