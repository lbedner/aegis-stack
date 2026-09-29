"""Fragments and files for the Overseer Storage page's browser: download,
upload into the open folder, and delete behind a confirmation. Mounted by
``routes/pages.py`` at ``overseer_storage.PARTIALS``.

The app's own bucket is read-only here (``overseer_storage.writable``):
its keys are content hashes that database rows point at.
"""

from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import overseer_storage
from app.components.web_frontend.overseer_nav import page_url
from app.components.web_frontend.rendering import dialog, go_to
from app.core.formatting import safe_filename
from app.core.storage import get_storage
from app.models.user import User
from app.services.auth.deps import get_optional_user

from .overseer_auth import signed_in

router = APIRouter(prefix=overseer_storage.PARTIALS)

BROWSE_PAGE = page_url("components", "storage") + "/browse"


def _store() -> Any:
    store = get_storage()
    if not hasattr(store, "fetch"):
        raise HTTPException(
            status_code=404, detail="The filesystem store is not browsed here."
        )
    return store


def _writable(store: Any, bucket: str) -> None:
    if not overseer_storage.writable(store, bucket):
        raise HTTPException(
            status_code=403, detail="The app's own bucket is written by the app."
        )


def _filename(key: str) -> str:
    return safe_filename(key.rsplit("/", 1)[-1], fallback="")


@router.get("/download")
async def download(
    bucket: str, key: str, user: User | None = Depends(get_optional_user)
) -> Response:
    """The object, as an attachment named after the last part of its key."""
    signed_in(user)
    found = await _store().fetch(bucket, key)
    if found is None:
        raise HTTPException(status_code=404)
    data, content_type = found
    return Response(
        data,
        media_type=content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(key) or "download"}"'
        },
    )


@router.get("/confirm-delete", response_class=HTMLResponse)
async def confirm_delete(
    request: Request,
    bucket: str,
    key: Annotated[list[str], Query()],
    user: User | None = Depends(get_optional_user),
) -> Response:
    """The confirmation for one file (the row menu) or many (the checked
    ones); its button sends the DELETE below."""
    signed_in(user)
    _writable(_store(), bucket)
    many = len(key) > 1
    target = urlencode({"bucket": bucket, "key": key}, doseq=True)
    return dialog(
        request,
        "pages/overseer/_confirm.html",
        title=f"Delete {len(key)} files?" if many else "Delete this file?",
        body=(
            f"{len(key)} files will be removed from {bucket}. This cannot be undone."
            if many
            else f"{key[0]} will be removed from {bucket}. This cannot be undone."
        ),
        url=f"{overseer_storage.PARTIALS}/object?{target}",
        label="Delete",
        method="delete",
        done=f"{len(key)} files deleted" if many else "File deleted",
    )


@router.delete("/object", status_code=204)
async def delete_objects(
    bucket: str,
    key: Annotated[list[str], Query()],
    user: User | None = Depends(get_optional_user),
) -> Response:
    signed_in(user)
    store = _store()
    _writable(store, bucket)
    await store.remove_many(bucket, key)
    return Response(status_code=204)


@router.post("/upload")
async def upload(
    bucket: Annotated[str, Form()],
    file: UploadFile,
    prefix: Annotated[str, Form()] = "",
    user: User | None = Depends(get_optional_user),
) -> Response:
    """Store the file in the open folder, then show that folder again."""
    signed_in(user)
    store = _store()
    _writable(store, bucket)
    name = _filename(file.filename or "")
    if not name:
        raise HTTPException(status_code=422, detail="The file needs a name.")
    await store.upload(bucket, prefix + name, await file.read(), file.content_type)
    return go_to(
        f"{BROWSE_PAGE}?{urlencode({'bucket': bucket, 'prefix': prefix})}",
        f"Uploaded {name}",
        target="#overseer-main",
    )
