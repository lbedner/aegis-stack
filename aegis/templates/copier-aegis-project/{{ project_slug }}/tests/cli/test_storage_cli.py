"""``storage check``: what a script reads is the missing keys alone on
stdout (``aegis deploy-upload-storage`` sends exactly those)."""

from pathlib import Path

import pytest

from app.cli import storage_cli
from app.core.storage import FilesystemStorage, content_key, set_storage
from tests._cli import invoke


@pytest.fixture(autouse=True)
def _store(tmp_path: Path) -> None:
    set_storage(FilesystemStorage(tmp_path))
    yield
    set_storage(None)


def _missing(monkeypatch: pytest.MonkeyPatch, keys: list[str]) -> None:
    """The check's answer; the shared test database holds other tests' rows."""

    async def missing(session: object) -> list[str]:
        return keys

    monkeypatch.setattr(storage_cli, "missing_objects", missing)


def test_check_prints_each_missing_key_alone_and_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone = [content_key(b"a"), content_key(b"b")]
    _missing(monkeypatch, gone)
    result = invoke(["storage", "check"])
    assert result.exit_code == 1
    assert result.output.split() == gone


def test_check_passes_quietly_on_stdout_when_nothing_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _missing(monkeypatch, [])
    result = invoke(["storage", "check"])
    assert result.exit_code == 0
    assert result.output == ""
