"""Regression tests for issue #870 — stale warn-only Dockerfiles."""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core import manual_updater
from aegis.core.manual_updater import ManualUpdater


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [(False, True, "css-build"), (True, False, "FROM python")],
)
def test_htmx_change_regenerates_pristine_warn_only_dockerfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    before: bool,
    after: bool,
    expected: str,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    renders = {
        False: "FROM python:3.13\n",
        True: "FROM node:22-alpine AS css-build\nFROM python:3.13\n",
    }
    dockerfile.write_text(renders[before])
    updater = ManualUpdater.__new__(ManualUpdater)
    updater.project_path = tmp_path
    updater.answers = {"include_htmx": before}
    monkeypatch.setattr(
        updater,
        "_render_template_file",
        lambda _template, answers: renders[answers["include_htmx"]],
    )
    monkeypatch.setattr(
        manual_updater,
        "SHARED_TEMPLATE_FILES",
        {"Dockerfile": {"overwrite": False, "backup": False, "warn": True}},
    )

    updated, _, need_merge = updater._regenerate_shared_files({"include_htmx": after})

    assert expected in dockerfile.read_text()
    assert dockerfile.read_text() == renders[after]
    assert "Dockerfile" in updated
    assert "Dockerfile" not in need_merge


def test_htmx_change_preserves_custom_dockerfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.13\nRUN custom-build-step\n")
    before = dockerfile.read_text()
    updater = ManualUpdater.__new__(ManualUpdater)
    updater.project_path = tmp_path
    updater.answers = {"include_htmx": False}
    monkeypatch.setattr(
        updater,
        "_render_template_file",
        lambda _template, answers: (
            "FROM node:22-alpine AS css-build\nFROM python:3.13\n"
            if answers["include_htmx"]
            else "FROM python:3.13\n"
        ),
    )
    monkeypatch.setattr(
        manual_updater,
        "SHARED_TEMPLATE_FILES",
        {"Dockerfile": {"overwrite": False, "backup": False, "warn": True}},
    )

    updated, _, need_merge = updater._regenerate_shared_files({"include_htmx": True})

    assert dockerfile.read_text() == before
    assert "Dockerfile" not in updated
    assert "Dockerfile" in need_merge
