"""``aegis init`` reads its template from ``AEGIS_TEMPLATE_PATH`` when set, as
``aegis update`` does. An installed CLI has no checkout of its own and clones
the template from GitHub; CI's uvx job did that twice a run, and so rendered
main's template rather than the pull request's."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from aegis.__main__ import app
from aegis.core import copier_updater
from aegis.core.copier_manager import generate_with_copier
from aegis.core.template_generator import TemplateGenerator

REPO = Path(__file__).parents[2]
INIT = ["init", "probe", "--no-interactive", "--yes", "--force"]


class _AskedError(Exception):
    pass


def test_generation_reads_the_template_it_is_handed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str | None] = []

    def record(override_path: str | None = None) -> Path:
        asked.append(override_path)
        raise _AskedError

    monkeypatch.setattr(copier_updater, "get_template_root", record)
    template_gen = TemplateGenerator(
        project_name="probe",
        selected_components=[],
        scheduler_backend="memory",
        selected_services=[],
    )

    with pytest.raises(_AskedError):
        generate_with_copier(template_gen, tmp_path, template_path="/a/checkout")

    assert asked == ["/a/checkout"]


def test_init_hands_generation_the_checkout_and_says_it_pins_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handed: list[Any] = []

    def record(
        template_gen: TemplateGenerator, output_dir: Path, **kwargs: Any
    ) -> Path:
        handed.append(kwargs.get("template_path"))
        return Path(output_dir) / template_gen.project_slug

    monkeypatch.setenv("AEGIS_TEMPLATE_PATH", str(REPO))
    monkeypatch.setattr("aegis.core.copier_manager.generate_with_copier", record)

    result = CliRunner().invoke(app, [*INIT, "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert handed == [str(REPO)]
    # The project records this machine's path as where it updates from.
    assert f"git+file://{REPO}" in result.output.replace("\n", "")


def test_a_bad_template_path_stops_init_before_force_removes_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kept = tmp_path / "probe" / "kept.txt"
    kept.parent.mkdir()
    kept.write_text("mine")
    monkeypatch.setenv("AEGIS_TEMPLATE_PATH", str(tmp_path / "no-such-checkout"))

    result = CliRunner().invoke(app, [*INIT, "--output-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert kept.read_text() == "mine"
