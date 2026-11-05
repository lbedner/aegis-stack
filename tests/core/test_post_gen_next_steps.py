"""The next steps after ``aegis init``: the ``cd`` line is what the user
would type from where they ran it."""

from pathlib import Path

import pytest

from aegis.core.post_gen_tasks import next_steps


def test_the_cd_line_is_relative_under_where_init_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert next_steps(tmp_path / "my-app")[0].strip() == "cd my-app"


def test_the_cd_line_stays_absolute_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "here").mkdir()
    monkeypatch.chdir(tmp_path / "here")

    assert next_steps(tmp_path / "my-app")[0].strip() == f"cd {tmp_path / 'my-app'}"
