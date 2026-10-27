"""What the app's buckets hold, as an agent's read (``storage``), as
Overseer's Storage browses them; files kept on disk are said to be."""

from typing import Any

import pytest

from app.core import storage as storage_seam
from app.core.tools import get_tool, result_data
from app.services.system import tools


class Bucketed:
    async def buckets(self) -> list[dict[str, Any]]:
        return [{"name": "my-app", "created": None}]

    async def browse(self, bucket: str, prefix: str, limit: int) -> dict[str, Any]:
        assert (bucket, prefix) == ("my-app", "docs/")
        return {
            "folders": ["docs/2026/"],
            "files": [{"key": "docs/receipt.pdf", "size": 432_000, "modified": None}],
            "truncated": False,
        }


async def test_the_buckets_and_what_one_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_seam, "get_storage", Bucketed)
    assert result_data(await tools.storage()) == {"buckets": ["my-app"]}
    assert result_data(await tools.storage(bucket="my-app", prefix="docs/")) == {
        "bucket": "my-app",
        "prefix": "docs/",
        "folders": ["docs/2026/"],
        "files": [{"key": "docs/receipt.pdf", "size": 432_000, "modified": None}],
        "truncated": False,
    }
    tool = get_tool("storage")
    assert tool is not None and tool.effect == "read" and tool.admin


async def test_files_kept_on_disk_are_said_to_be(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(storage_seam, "get_storage", object)
    with pytest.raises(ValueError, match="filesystem"):
        await tools.storage()
