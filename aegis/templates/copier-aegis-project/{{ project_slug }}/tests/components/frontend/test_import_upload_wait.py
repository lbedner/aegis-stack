"""The upload-progress event fires when the browser has sent the last
byte; the server may still be writing. The import must wait for the file,
not report "did not arrive" while it is arriving."""

import asyncio
from pathlib import Path

import pytest

from app.components.frontend.dashboard.modals.finance_modal.transactions_panel.imports_flow import (
    _settled_upload,
)


@pytest.mark.asyncio
async def test_a_late_file_is_still_read_then_removed(tmp_path: Path) -> None:
    target = tmp_path / "abc-statement.csv"

    async def _arrives_late() -> None:
        await asyncio.sleep(0.15)
        target.write_bytes(b"Date,Amount\n")

    asyncio.get_running_loop().create_task(_arrives_late())
    data = await _settled_upload(target, attempts=20, pause=0.05)

    assert data == b"Date,Amount\n"
    assert not target.exists()


@pytest.mark.asyncio
async def test_a_file_that_never_arrives_is_none(tmp_path: Path) -> None:
    assert await _settled_upload(tmp_path / "missing.csv", attempts=3, pause=0.01) is None
