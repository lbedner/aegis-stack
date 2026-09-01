"""Browser-upload plumbing shared by every FilePicker flow.

One signer for the dashboard-mounted flet upload endpoint, and one
pick-upload-read cycle on top of it, used by the register's file imports,
chat's image attachments, and the document store alike.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

import flet as ft

from app.components.frontend.controls.snack_bar import ErrorSnackBar
from app.core.config import settings
from app.core.constants import dashboard_upload_dir
from app.core.log import logger


def signed_upload_url(server_name: str, *, expires_seconds: int = 600) -> str:
    """Signed URL for the dashboard-mounted flet upload endpoint.

    ``page.get_upload_url`` cannot be used here: the Flet app is mounted
    at ``/dashboard``, so flet would sign its sub-app-relative endpoint
    while the server verifies the externally visible path
    (``request.url.path`` includes the mount prefix). Signing the
    external path directly satisfies both the route and the check.
    """
    from flet_web.uploads import build_upload_url

    return build_upload_url(
        "/dashboard/upload", server_name, expires_seconds, settings.SECRET_KEY
    )


class BrowserUploads:
    """Pick files in the browser and hand their bytes to ``on_file``.

    A browser pick has no local path, so each file first streams to the
    signed ``/dashboard/upload`` endpoint; when the picker reports it
    complete the bytes are read server-side, the temp file removed, and
    ``on_file(name, data)`` awaited. Picker events name files by their
    local filename and one batch can hold several with the same name (a
    scanner's default), so each name keeps a queue of server-side names
    rather than a single slot. ``on_change`` fires whenever the set in
    flight changes, for a "receiving" indicator.
    """

    def __init__(
        self,
        on_file: Callable[[str, bytes], Awaitable[None]],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._on_file = on_file
        self._on_change = on_change
        self._in_flight: dict[str, list[str]] = {}
        self.picker = ft.FilePicker(
            on_result=self._on_picked, on_upload=self._on_progress
        )

    def mount(self, page: ft.Page) -> None:
        """The picker renders only from ``page.overlay``; safe to repeat."""
        if self.picker not in page.overlay:
            page.overlay.append(self.picker)

    @property
    def in_flight(self) -> bool:
        return bool(self._in_flight)

    def pick(
        self,
        *,
        dialog_title: str,
        allow_multiple: bool = True,
        allowed_extensions: list[str] | None = None,
    ) -> None:
        self.picker.pick_files(
            dialog_title=dialog_title,
            allow_multiple=allow_multiple,
            allowed_extensions=allowed_extensions,
        )

    def _on_picked(self, event: ft.FilePickerResultEvent) -> None:
        if not event.files:
            return
        uploads: list[ft.FilePickerUploadFile] = []
        for picked in event.files:
            name = picked.name or "file"
            server_name = f"{uuid4().hex}-{name}"
            self._in_flight.setdefault(name, []).append(server_name)
            uploads.append(
                ft.FilePickerUploadFile(name, upload_url=signed_upload_url(server_name))
            )
        self.picker.upload(uploads)
        self._changed()

    def _on_progress(self, event: ft.FilePickerUploadEvent) -> None:
        if event.error:
            self._take(event.file_name)
            self._error(f"Upload failed: {event.error}")
            self._changed()
            return
        if (event.progress or 0) >= 1.0 and self.picker.page is not None:
            self.picker.page.run_task(self._arrived, event.file_name)

    async def _arrived(self, name: str) -> None:
        """The upload landed: read it, drop the temp file, hand it over."""
        server_name = self._take(name)
        if server_name is None:
            return
        path = dashboard_upload_dir() / server_name
        try:
            data = path.read_bytes()
        except OSError:
            logger.warning("browser_upload.missing", name=name)
            self._error(f"{name} did not arrive on the server.")
            return
        finally:
            path.unlink(missing_ok=True)
            self._changed()
        await self._on_file(name, data)

    def _take(self, name: str) -> str | None:
        """The next server-side name queued under this local filename."""
        queue = self._in_flight.get(name)
        if not queue:
            return None
        server_name = queue.pop(0)
        if not queue:
            del self._in_flight[name]
        return server_name

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _error(self, message: str) -> None:
        if self.picker.page is not None:
            ErrorSnackBar(message).launch(self.picker.page)
