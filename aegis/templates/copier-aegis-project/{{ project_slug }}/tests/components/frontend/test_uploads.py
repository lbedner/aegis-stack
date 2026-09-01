"""The browser upload cycle, minus the browser.

A batch can carry two files with the same local name (a scanner's
default), and the picker reports completions by that name alone. Each
name keeps a queue, so both files land and neither is mistaken for the
other.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.components.frontend.controls import uploads
from app.components.frontend.controls.uploads import BrowserUploads


@pytest.fixture
def picked(monkeypatch: pytest.MonkeyPatch) -> tuple[BrowserUploads, list]:
    seen: list[tuple[str, bytes]] = []

    async def on_file(name: str, data: bytes) -> None:
        seen.append((name, data))

    up = BrowserUploads(on_file)
    sent: list = []
    up.picker.upload = lambda files: sent.extend(files)  # type: ignore[method-assign]
    monkeypatch.setattr(
        uploads, "signed_upload_url", lambda server_name: f"/u/{server_name}"
    )
    up._on_picked(
        SimpleNamespace(
            files=[SimpleNamespace(name="scan.pdf"), SimpleNamespace(name="scan.pdf")]
        )
    )
    assert len(sent) == 2
    return up, seen


def test_same_named_files_each_keep_their_own_upload(picked) -> None:
    up, _ = picked
    assert up.in_flight

    first = up._take("scan.pdf")
    second = up._take("scan.pdf")

    assert first and second and first != second
    assert up._take("scan.pdf") is None
    assert not up.in_flight


def test_an_arrived_upload_is_read_handed_over_and_removed(
    picked, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    up, seen = picked
    monkeypatch.setattr(uploads, "dashboard_upload_dir", lambda: tmp_path)
    server_name = up._in_flight["scan.pdf"][0]
    (tmp_path / server_name).write_bytes(b"%PDF")

    asyncio.run(up._arrived("scan.pdf"))

    assert seen == [("scan.pdf", b"%PDF")]
    assert not (tmp_path / server_name).exists()
    assert up.in_flight  # the second scan.pdf is still coming
