"""The version gate must not go quiet when it cannot read a version.

A project stamped ``_template_version: HEAD`` parses to nothing, so
``check_version_compatibility`` returns UNKNOWN - which
``validate_version_compatibility`` used to fall off the end of, silently.
That project is then never told its CLI and template have diverged, across
a major version included (aegis-stack#1136).
"""

from pathlib import Path

import pytest
import typer

from aegis.core.version_compatibility import (
    VersionCompatibility,
    check_version_compatibility,
    validate_version_compatibility,
)


def test_unparseable_template_version_is_unknown() -> None:
    assert check_version_compatibility("0.11.1", "HEAD") == VersionCompatibility.UNKNOWN


def test_unknown_warns_and_does_not_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import aegis.core.version_compatibility as vc

    monkeypatch.setattr(vc, "get_cli_version", lambda: "0.11.1")
    monkeypatch.setattr(vc, "get_project_template_version", lambda path: "HEAD")

    validate_version_compatibility(tmp_path, command_name="add")

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "HEAD" in output, "unreadable template version passed silently"


@pytest.fixture
def cli_015(monkeypatch: pytest.MonkeyPatch) -> None:
    import aegis.core.version_compatibility as vc

    monkeypatch.setattr(vc, "get_cli_version", lambda: "0.15.0")


def _project(tmp_path: Path, template_version: str, aegis_version: str) -> Path:
    (tmp_path / ".copier-answers.yml").write_text(
        f"_template_version: {template_version}\naegis_version: {aegis_version}\n"
    )
    return tmp_path


@pytest.mark.parametrize("stamp", ["HEAD", "dev"])
def test_an_unversioned_stamp_is_gated_by_the_cli_that_generated_it(
    tmp_path: Path, cli_015: None, capsys: pytest.CaptureFixture[str], stamp: str
) -> None:
    """A 0.12 project stamped ``HEAD`` met by a 0.15 CLI: an add there was a
    partial upgrade with conflicts (#1532). The CLI that generated it says
    which release it is, so the gate holds."""
    with pytest.raises(typer.Exit):
        validate_version_compatibility(_project(tmp_path, stamp, "0.12.1"))

    assert "aegis update" in capsys.readouterr().err


def test_force_still_goes_through(tmp_path: Path, cli_015: None) -> None:
    validate_version_compatibility(_project(tmp_path, "HEAD", "0.12.1"), force=True)


def test_a_dev_project_from_this_release_is_not_gated(
    tmp_path: Path, cli_015: None
) -> None:
    validate_version_compatibility(_project(tmp_path, "dev", "0.15.0"))


def test_a_corrupt_answers_file_warns_instead_of_crashing(
    tmp_path: Path, cli_015: None
) -> None:
    (tmp_path / ".copier-answers.yml").write_text("_template_version: [unclosed\n")

    validate_version_compatibility(tmp_path)
