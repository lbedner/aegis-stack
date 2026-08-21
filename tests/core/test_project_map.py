"""The project map lists what was actually generated.

The service section is derived from the service registry, so every service
appears the moment its directory exists. It used to name three services by
hand, which silently hid finance, payment, insights, and blog from the
post-generation tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aegis.core.project_map import render_project_map
from aegis.core.services import SERVICES


def _skeleton(root: Path, *service_dirs: str) -> Path:
    """A minimal generated-project shape with the given service dirs."""
    project = root / "demo"
    (project / "app" / "components" / "backend").mkdir(parents=True)
    (project / "app" / "entrypoints").mkdir(parents=True)
    for name in service_dirs:
        (project / "app" / "services" / name).mkdir(parents=True)
    return project


class TestServiceSection:
    @pytest.mark.parametrize("service", sorted(SERVICES))
    def test_every_registered_service_is_listed(
        self, service: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_project_map(_skeleton(tmp_path, service))
        out = capsys.readouterr().out
        assert f"{service}/" in out, f"{service} missing from the project map"

    def test_lists_several_together(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_project_map(_skeleton(tmp_path, "ai", "finance"))
        out = capsys.readouterr().out
        assert "ai/" in out
        assert "finance/" in out
        # Registry order, not filesystem order: ai precedes finance.
        assert out.index("ai/") < out.index("finance/")

    def test_non_service_directories_are_not_listed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # app/services/ also holds shared plumbing that is not a service.
        render_project_map(_skeleton(tmp_path, "shared", "system", "finance"))
        out = capsys.readouterr().out
        assert "finance/" in out
        assert "shared/" not in out
        assert "system/" not in out

    def test_section_omitted_without_services(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_project_map(_skeleton(tmp_path))
        assert "services/" not in capsys.readouterr().out

    def test_every_service_has_a_map_label(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No service should render with an empty or missing annotation.
        for service in SERVICES:
            render_project_map(_skeleton(tmp_path / service, service))
            line = next(
                ln for ln in capsys.readouterr().out.splitlines() if f"{service}/" in ln
            )
            _, _, annotation = line.partition("←")
            label = annotation.strip()
            assert label, f"{service} has no project-map label"
            # Tree rows are one line: a registry description used as a
            # fallback is prose, and prose does not fit here.
            assert len(label) <= 30, f"{service} label too long for the tree: {label}"
            assert "xperimental" not in label
